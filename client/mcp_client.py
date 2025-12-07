
import json
import os
import re
import sys
import asyncio
import logging

from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Ensure log directory exists
os.makedirs("logs", exist_ok=True)

# Set up logger
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/mcp_client.log"),
        logging.StreamHandler()
    ]
)


class MCPClient:
    """
    Generic MCP client that can talk to:
      - local stdio-based MCP servers (Python/Node)
      - remote SSE-based MCP servers
      - remote HTTP-based MCP servers (POST with streaming)

    Usage examples:
      python mcp_client.py --stdio path/to/server.py
      python mcp_client.py --stdio path/to/server.js
      python mcp_client.py --sse http://localhost:8080/sse
      python mcp_client.py --http http://localhost:8080/mcp
    """

    def __init__(self):
        self.session = None
        self.exit_stack = AsyncExitStack()
        self._connected_via: Optional[str] = None # "stdio" or "sse"

        # Initialize the Azure OpenAI client
        model_name = os.getenv("AZURE_OPENAI_MODEL")
        deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION")

        print(f"Using Azure OpenAI Model: {model_name} (Deployment: {deployment_name})")
        print(f"Azure OpenAI Endpoint: {endpoint}")
        print(f"Azure OpenAI API Version: {api_version}")
        print(f"Azure OpenAI API Key: {'SET' if api_key else 'NOT SET'}")

        if not endpoint or not api_key:
            logger.warning("Azure OpenAI credentials not fully configured. Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY.")

        self.openai = OpenAI(
            base_url=endpoint,
            api_key=api_key
        )
        self.model_name = model_name

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------ 
    async def connect_to_sse_server(self, server_url: str):
        """
        Connect to an SSE MCP server.
        """
        logger.debug(f"Connecting to SSE MCP server at {server_url}")

        self._streams_context = sse_client(url=server_url)
        read_stream, write_stream = await self._streams_context.__aenter__()

        self._session_context = ClientSession(read_stream, write_stream)
        self.session = await self._session_context.__aenter__()

        # Initialize connection state
        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        logger.info(f"Connected to SSE MCP Server at {server_url}. ")
        logger.info(f"Available tools: {[tool.name for tool in tools]}")
    
    async def connect_to_http_server(self, server_url: str):
        """
        Connect to an HTTP-based MCP server (streaming HTTP).
        Uses HTTP POST with JSON-RPC 2.0 messages.
        """
        logger.debug(f"Connecting to Streamable HTTP MCP server at {server_url}")

        self._http_context = streamablehttp_client(url=server_url)
        read_stream, write_stream, get_session_id = await self._http_context.__aenter__()

        self._session_context = ClientSession(read_stream, write_stream)
        self.session = await self._session_context.__aenter__()

        # Initialize connection state
        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        logger.info(f"Connected to Streamable HTTP MCP Server at {server_url}.")
        logger.info(f"Available tools: {[tool.name for tool in tools]}")
        self._connected_via = "http"

    async def connect_to_stdio_server(self, server_script_path: str, extra_args: list[str] | None = None):
        """
        Connect to a stdio MCP server.
        """
        is_python = False
        is_javascript = False
        command = None

        if extra_args is None:
            extra_args = []

        # Detect npm package vs file path
        # Heuristic:
        #   - starts with '@'  => scoped npm package
        #   - no '/'           => treat as npm package name
        if server_script_path.startswith("@") or "/" not in server_script_path:
            # npm package: use npx
            is_javascript = True
            command = "npx"

            # If user explicitly passed "-y", don't add it again.
            # Otherwise, default to "-y" so npx doesn't prompt interactively.
            if extra_args and extra_args[0] == "-y":
                args = [server_script_path, *extra_args]
            else:
                args = ["-y", server_script_path, *extra_args]
        else:
            # Local file path
            is_python = server_script_path.endswith(".py")
            is_javascript = server_script_path.endswith(".js")

            if not (is_python or is_javascript):
                raise ValueError("Server script must be a .py, .js file or npm package.")
            
            command = "python" if is_python else "node"
            args = [server_script_path, *extra_args]
        
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=None
        )

        logger.debug(f"Connecting to stdio MCP server with command: {command} and args: {args}")

        # Start the server
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.writer = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.writer))
        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        logger.info(f"Connected to stdio MCP Server using {command} {args}. ")
        logger.info(f"Available tools: {[tool.name for tool in tools]}")


    async def connect_to_server(self, server_path_or_url: str, extra_args: list[str] | None = None):
        """
        Connect to an MCP server (either stdio or SSE).
        """

        # Check if the input is a URL (for SSE server)
        url_pattern = re.compile(r'^(http|https)://')

        if url_pattern.match(server_path_or_url):
            # It's a URL - try SSE first, then fall back to Streamable HTTP
            logger.info(f"Detected URL: {server_path_or_url}")
            try:
                await self.connect_to_sse_server(server_path_or_url)
            except Exception as e:
                logger.warning(f"SSE connection failed: {e}. Trying Streamable HTTP...")
                try:
                    await self.connect_to_http_server(server_path_or_url)
                except Exception as http_error:
                    logger.error(f"Both SSE and HTTP connections failed: {http_error}")
                    raise
        else:
            # It's a script path - connect to stdio server
            await self.connect_to_stdio_server(server_path_or_url, extra_args=extra_args or [])
        
    async def process_query(self, query: str, previous_messages: list = None) -> tuple[str, list]:
        """
        Process a query using the MCP server and available tools.
        """
        if not self.session:
            raise RuntimeError("Client session is not initialized.")
        
        messages = []
        if previous_messages:
            messages.extend(previous_messages)

        messages.append(
            {
                "role": "user",
                "content": query
            }
        )

        response = await self.session.list_tools()
        available_tools = [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.inputSchema) if tool.inputSchema else {}
            }
        } for tool in response.tools]


        # Initialize OpenAI API call
        logger.info(f"Sending query to {self.model_name}: {query}")
        completion = self.openai.chat.completions.create(
            model=self.model_name,
            messages=messages,
            tools=available_tools
        )

        # Process the response and handle tool calls
        final_response = []
        assistant_message = completion.choices[0].message

        if assistant_message.content:
            final_response.append(assistant_message.content)
        
        if assistant_message.tool_calls:
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                # Execute tool call
                logger.debug(f"Calling tool {tool_name} with args {tool_args}...")
                result = await self.session.call_tool(tool_name, tool_args)
                final_response.append(f"[Calling tool {tool_name}]")

                # Add assistant message to conversation
                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": tool_call.function.arguments
                            }
                        }
                    ]
                })

                # Add tool result to conversation
                tool_result_content = str(result.content) if hasattr(result, 'content') else str(result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": tool_result_content
                })

                # Get the next response from model
                next_completion = self.openai.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=available_tools
                )

                next_message = next_completion.choices[0].message
                if next_message.content:
                    final_response.append(next_message.content)
                
                messages.append({
                    "role": "assistant",
                    "content": next_message.content or ""
                })
            
        return "\n".join(final_response), messages
    
    async def chat_loop(self):
        """
        Run an interactive chat loop with the server.
        """
        previous_messages = []
        print("Type your queries or 'quit' to exit.")

        while True:
            try:
                query = input("\nQuery: ").strip()
                if query.lower() in ["quit", "exit"]:
                    break

                # Check if the user wants to refresh conversation (history)
                if query.lower() == "refresh":
                    previous_messages = []

                response, previous_messages = await self.process_query(query=query, previous_messages=previous_messages)
                print(f"\nResponse: {response}")
            except Exception as e:
                logger.error(f"Error processing query: {e}")
                print(f"Error: {e}")
        
    async def cleanup(self):
            """Clean up resources on exit."""
            await self.exit_stack.aclose()
            if hasattr(self, '_session_context') and self._session_context:
                await self._session_context.__aexit__(None, None, None)
            if hasattr(self, '_streams_context') and self._streams_context:
                await self._streams_context.__aexit__(None, None, None)
            if hasattr(self, '_http_context') and self._http_context:
                await self._http_context.__aexit__(None, None, None)

        
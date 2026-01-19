
import json
import os
import re
import logging
from pathlib import Path

from typing import Optional
from contextlib import AsyncExitStack
from rich.console import Console

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from openai import OpenAI
console = Console()


STRICT_SYSTEM_PROMPT = """You are a careful assistant.

Safety / reliability policy (generic):
- Do NOT invent facts, identifiers, schemas, commands, configuration keys, APIs, file names, URLs, or query syntax.
- If the user request is underspecified or depends on unknown context, ask 1–3 targeted clarifying questions.
- If you still cannot determine the correct answer from the conversation and tool outputs, say you don't know.
- If you provide an example, label it clearly as a template/pseudocode and use placeholders rather than guessing real names.

Tool-grounding policy:
- Prefer using available tools to look up or verify details.
- Only cite sources that come directly from tool outputs.
"""

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

    def __init__(self, llm_config: dict | None = None, instructions: str | None = None):
        self.session = None
        self.exit_stack = AsyncExitStack()
        self._connected_via: Optional[str] = None # "stdio" or "sse"

        self.llm_config: dict | None = llm_config
        self.instructions: str | None = instructions
        self.base_instructions: str | None = self._load_base_instructions()
        self.openai: OpenAI | None = None
        self.model_name: str | None = None

        self.strict_mode = os.getenv("MCP_STRICT_MODE", "true").strip().lower() not in {"0", "false", "no", "off"}

        # Some models/endpoints reject custom temperature values (e.g., only the default is allowed).
        # If AZURE_OPENAI_TEMPERATURE isn't set, omit the parameter entirely.
        self.temperature: float | None
        raw_temp = os.getenv("AZURE_OPENAI_TEMPERATURE")
        if raw_temp is None or not raw_temp.strip():
            self.temperature = None
        else:
            try:
                self.temperature = float(raw_temp)
            except ValueError:
                self.temperature = None

    @staticmethod
    def _default_base_instructions_path() -> Path:
        # Repo layout: <root>/client/mcp_client.py and <root>/InstructionFiles/copilot-instructions.md
        return Path(__file__).resolve().parent.parent / "InstructionFiles" / "copilot-instructions.md"

    @staticmethod
    def _strip_instructions_fence(text: str) -> str:
        """If the text is wrapped in a ```instructions fenced block, return its inner content."""
        normalized = (text or "").replace("\r\n", "\n").strip()
        if not normalized:
            return ""
        if not normalized.startswith("```instructions"):
            return normalized

        first_newline = normalized.find("\n")
        if first_newline == -1:
            return normalized

        closing = normalized.rfind("\n```")
        if closing == -1 or closing <= first_newline:
            return normalized

        return normalized[first_newline + 1 : closing].strip()

    def _load_base_instructions(self) -> str | None:
        try:
            p = self._default_base_instructions_path()
            if not p.exists():
                return None
            content = p.read_text(encoding="utf-8")
            content = self._strip_instructions_fence(content)
            return content or None
        except Exception:
            # Base instructions are optional; failure should not block the CLI.
            return None

    def _resolve_value(self, value: str | None) -> str | None:
        if not value:
            return value
        if value.startswith("env:"):
            return os.getenv(value.split(":", 1)[1])
        return value

    def _ensure_openai_client(self) -> None:
        if self.openai is not None:
            return

        if not self.llm_config:
            raise RuntimeError("No LLM profile selected. Add/select an LLM profile before starting chat.")

        endpoint = self._resolve_value(str(self.llm_config.get("endpoint", "") or ""))
        api_key = self._resolve_value(str(self.llm_config.get("api_key", "") or ""))
        model = self._resolve_value(str(self.llm_config.get("model", "") or ""))

        if not endpoint:
            raise RuntimeError("LLM profile is missing 'endpoint'.")
        if not api_key:
            raw_key = str(self.llm_config.get("api_key", "") or "")
            if raw_key.startswith("env:"):
                var_name = raw_key.split(":", 1)[1]
                raise RuntimeError(
                    "LLM profile api_key is set to 'env:%s' but that environment variable is not set. "
                    "Edit the LLM profile to store a literal API key (current supported mode), or set the env var in your shell."
                    % var_name
                )
            raise RuntimeError("LLM profile is missing 'api_key'.")
        if not model:
            raise RuntimeError("LLM profile is missing 'model' (Azure: deployment name).")

        # Note: For now we only support API key authentication.
        # Many Azure OpenAI-style endpoints expect the header name `api-key`.
        self.openai = OpenAI(
            base_url=endpoint,
            api_key=api_key,
            default_headers={"api-key": api_key},
        )
        self.model_name = model

    def _ensure_system_message(self, messages: list[dict]) -> list[dict]:
        needs_system = bool(self.base_instructions) or self.strict_mode or bool(self.instructions)
        if not needs_system:
            return messages

        parts: list[str] = []
        if self.base_instructions:
            parts.append(self.base_instructions)
        if self.strict_mode:
            parts.append("# Strict mode\n" + STRICT_SYSTEM_PROMPT)
        if self.instructions:
            user_inst = self._strip_instructions_fence(self.instructions)
            if user_inst:
                parts.append("# User instruction file\n" + user_inst)
        combined = "\n\n".join(parts).strip()

        if messages and messages[0].get("role") == "system":
            existing = str(messages[0].get("content") or "")
            if combined:
                messages[0]["content"] = (combined + "\n\n" + existing).strip() if existing else combined
            return messages

        return ([{"role": "system", "content": combined}] if combined else []) + list(messages)

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
        # logger.info(f"Available tools: {[tool.name for tool in tools]}")
    
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
        # logger.info(f"Available tools: {[tool.name for tool in tools]}")
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
        # logger.info(f"Available tools: {[tool.name for tool in tools]}")

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

        messages = self._ensure_system_message(messages)

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
        self._ensure_openai_client()
        logger.info(f"Sending query to {self.model_name}: {query}")
        def _create_completion():
            kwargs = {
                "model": self.model_name,
                "messages": messages,
                "tools": available_tools,
            }
            if self.temperature is not None:
                kwargs["temperature"] = self.temperature
            return self.openai.chat.completions.create(**kwargs)

        try:
            completion = _create_completion()
        except Exception as e:
            # Some models only allow the default temperature. If so, retry once without it.
            msg = str(e)
            if self.temperature is not None and "temperature" in msg and "Only the default" in msg:
                logger.warning("Model rejected temperature=%s; retrying without temperature.", self.temperature)
                self.temperature = None
                completion = _create_completion()
            else:
                raise

        # Process the response and handle tool calls
        final_response = []
        citations = []
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
                
                # Extract tool result content
                tool_result_content = str(result.content) if hasattr(result, 'content') else str(result)
                
                # Parse citations from tool result if it's JSON
                try:
                    if isinstance(result.content, str):
                        result_data = json.loads(result.content) if result.content.startswith('[') else result.content
                        if isinstance(result_data, list):
                            for item in result_data:
                                if isinstance(item, dict) and 'contentUrl' in item:
                                    citations.append({
                                        'title': item.get('title', 'Unknown'),
                                        'url': item.get('contentUrl', '')
                                    })
                except (json.JSONDecodeError, AttributeError):
                    pass

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
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": tool_result_content
                })

                # Get the next response from model for summarization
                with console.status("[bold green]Thinking..."):
                    try:
                        next_completion = _create_completion()
                    except Exception as e:
                        msg = str(e)
                        if self.temperature is not None and "temperature" in msg and "Only the default" in msg:
                            logger.warning("Model rejected temperature=%s; retrying without temperature.", self.temperature)
                            self.temperature = None
                            next_completion = _create_completion()
                        else:
                            raise

                next_message = next_completion.choices[0].message
                if next_message.content:
                    final_response.append(next_message.content)
                
                messages.append({
                    "role": "assistant",
                    "content": next_message.content or ""
                })
            
        # Format final response with citations
        formatted_response = "\n".join(final_response)
        
        if citations:
            formatted_response += "\n\n## Sources\n"
            for i, citation in enumerate(citations, 1):
                formatted_response += f"{i}. [{citation['title']}]({citation['url']})\n"
        
        return formatted_response, messages
    
    async def chat_loop(self):
        """
        Run an interactive chat loop with the server.
        """
        previous_messages = []
        print("Type your queries or 'quit' to exit.")

        while True:
            try:
                query = input("\nQuery: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nExiting chat...")
                break

            if not query:
                continue

            if query.lower() in ["quit", "exit"]:
                break

            # Check if the user wants to refresh conversation (history)
            if query.lower() == "refresh":
                previous_messages = []
                continue

            try:
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

        
# MCP Client

A universal command-line client for interacting with Model Context Protocol (MCP) servers. Supports stdio, SSE, and HTTP-based transports with Azure OpenAI integration for intelligent tool invocation.

## Features

- **Multiple Transport Protocols**

  - Stdio (local Python/Node servers and npm packages)
  - SSE (Server-Sent Events)
  - Streamable HTTP (JSON-RPC over HTTP POST)
  - Auto-detection and fallback between SSE and HTTP

- **Tool Execution**

  - Automatic tool discovery from MCP servers
  - Azure OpenAI integration for intelligent tool selection
  - Multi-turn conversations with tool call handling
  - Conversation history management

- **Developer Friendly**
  - Comprehensive logging to `logs/mcp_client.log`
  - Support for passing extra arguments to stdio servers
  - Interactive chat loop with refresh capability

## Installation

### From Source

```bash
# Clone or download the repository
cd mcp-client

# Install with UV (recommended)
uv sync

# Or with pip
pip install -e .
```

### Requirements

- Python 3.13+
- Azure OpenAI API credentials (for tool execution)

## Configuration

Set these environment variables before running:

```bash
# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-api-key>
AZURE_OPENAI_MODEL=gpt-5-nano
AZURE_OPENAI_DEPLOYMENT_NAME=<your-deployment>
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

Create a `.env` file in the project root with these variables, or set them in your shell.

## Usage

### Basic Command

```bash
mcp-client <server_script_path_or_url> [extra_args...]
```

### Examples

| Server Type                | Command                                                        |
| -------------------------- | -------------------------------------------------------------- |
| NPM Package (Playwright)   | `mcp-client @playwright/mcp@latest`                            |
| NPM Package (Azure DevOps) | `mcp-client @azure-devops/mcp contoso -d core work work-items` |
| Local Python Server        | `mcp-client ./weather.py`                                      |
| Local JavaScript Server    | `mcp-client ./server.js`                                       |
| SSE-based MCP Server       | `mcp-client http://localhost:3000/sse`                         |
| HTTP-based MCP Server      | `mcp-client http://localhost:3000/mcp`                         |
| Microsoft Learn MCP Server | `mcp-client https://learn.microsoft.com/api/mcp`               |

### Interactive Mode

Once connected, you'll be presented with an interactive prompt:

```
Query: What are the use cases of MCP?
```

Type your queries to interact with the MCP server's tools. The client will:

1. Send your query to Azure OpenAI
2. Identify relevant tools to call
3. Execute those tools
4. Return results to you

#### Special Commands

- `quit` or `exit` — Close the client
- `refresh` — Clear conversation history

## Architecture

### Core Components

- **MCPClient** — Main class handling all MCP server communication
  - `connect_to_server()` — Auto-detect and connect to any MCP server
  - `connect_to_sse_server()` — SSE transport handler
  - `connect_to_http_server()` — Streamable HTTP handler
  - `connect_to_stdio_server()` — Stdio transport handler
  - `process_query()` — Azure OpenAI integration for tool invocation
  - `chat_loop()` — Interactive user interface

### Transport Selection

The client automatically detects the server type:

- **URL (http/https)** → Tries SSE first, falls back to HTTP
- **File path (.py/.js)** → Uses stdio transport
- **Package name** (e.g., `@playwright/mcp`) → Uses npx + stdio

## Logging

All activity is logged to `client/logs/mcp_client.log`. Check this file for:

- Connection details
- Available tools from each server
- Query processing information
- Tool execution results
- Error diagnostics

## Development

### Project Structure

```
mcp-client/
├── client/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point
│   ├── mcp_client.py        # Core MCPClient class
│   └── logs/                # Generated logs
├── pyproject.toml           # Package metadata
├── README.md                # This file
└── requirements.txt         # Dependencies (optional)
```

### Running in Development Mode

```bash
# From the project root
python -m client https://learn.microsoft.com/api/mcp
```

### Building

```bash
uv pip install build
python -m build
```

This creates:

- `dist/mcp_client-0.1.0-py3-none-any.whl` (wheel)
- `dist/mcp_client-0.1.0.tar.gz` (source)

## Troubleshooting

### "ModuleNotFoundError: No module named 'client'"

- Ensure you've run `uv sync` from the project root

### "mcp-client: command not found"

- Activate your virtual environment: `.venv\Scripts\Activate.ps1` (PowerShell) or `source .venv/bin/activate` (Linux/Mac)
- Reinstall: `uv sync`

### Azure OpenAI Errors

- Verify your `.env` file or environment variables are set
- Check that your deployment name matches your model

### Connection Failures

- For URLs: Check network connectivity and that the endpoint is accessible
- For local servers: Verify the file path is correct
- Check `client/logs/mcp_client.log` for detailed error information

## Security

- Never commit `.env` files with real credentials
- Use environment variables or secure credential managers in production
- Rotate Azure OpenAI API keys regularly

## License

MIT License — See LICENSE file for details

## Support

For issues or questions:

1. Check `client/logs/mcp_client.log` for detailed diagnostics
2. Verify Azure OpenAI credentials and configuration
3. Ensure the MCP server is running and accessible
4. Review the examples above for your use case

## Contributing

Contributions welcome! Feel free to submit issues or pull requests.

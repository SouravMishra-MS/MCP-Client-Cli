# MCP Client

A command-line client for interacting with Model Context Protocol (MCP) servers. Supports stdio, SSE, and HTTP-based transports, with Azure OpenAI integration for tool calling.

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

### LLM profiles (llms.json)

This client uses LLM profiles stored in `llms.json` (managed via the CLI).

To manage profiles:

```bash
mcp-client -l
```

Profiles look like:

```json
[
  {
    "name": "default-azure-openai",
    "type": "azure_openai",
    "endpoint": "https://<your-resource>.openai.azure.com/openai/v1/",
    "api_key": "<YOUR_API_KEY>",
    "model": "<your-deployment-name>",
    "api_version": "2024-12-01-preview"
  }
]
```

Notes:

- Currently only API key auth is supported.
- For Azure OpenAI OpenAI-compatible endpoints, `model` is your deployment name.

### Instruction files (instruction_files.json)

You can store one or more markdown instruction files (for example, internal Copilot instruction prompts) and apply one during a chat session.

- In interactive mode: choose **i = manage instruction files** to list/add/delete saved files.
- Save an instruction file path: `mcp-client -i` (prompts) or `mcp-client -i <path>`.
- Use an instruction file for one chat run: `mcp-client -c -i <path>`.
- If you run `mcp-client -c` without `-i`, the client will ask if you want to use a saved instruction file.

Example:

```bash
mcp-client -c -i InstructionFiles/copilot-instructions.md
```

### Guardrails (reducing hallucinations)

This client can run in a strict mode that discourages the LLM from making up details. In strict mode, the assistant should:

- Ask 1–3 clarifying questions when key context is missing
- Avoid inventing schemas/identifiers/commands/config keys
- Say it doesn't know when it cannot determine the correct answer from the conversation and tool outputs
- Clearly label any examples as templates with placeholders

Configure with these environment variables:

```bash
# Strict mode (default: true)
MCP_STRICT_MODE=true

# Lower temperature reduces creative guesswork (default: 0)
AZURE_OPENAI_TEMPERATURE=0
```

## Usage

### Quick start (recommended)

1. Install dependencies:

```bash
uv sync
```

2. Add an LLM profile:

```bash
mcp-client -l
```

3. Start chat (you will select an LLM profile and MCP server):

```bash
mcp-client -c
```

### Basic command

```bash
mcp-client <server_script_path_or_url> [extra_args...]
```

If you want to apply an instruction file for this run:

```bash
mcp-client <server_script_path_or_url> -i InstructionFiles/copilot-instructions.md
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

If you run `mcp-client` with no arguments, you will see a simple menu:

```
Options: m=manage MCP servers, l=manage LLM profiles, i=manage instruction files, c=chat, q=quit
```

In chat mode, type your question and the client will call tools as needed.

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

All activity is logged to `logs/mcp_client.log`. Check this file for:

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
├── logs/                    # Generated logs
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

- Verify `llms.json` has a valid profile and you selected it
- Check that your deployment name matches `model`

### Connection Failures

- For URLs: Check network connectivity and that the endpoint is accessible
- For local servers: Verify the file path is correct
- Check `client/logs/mcp_client.log` for detailed error information

## Security

- `llms.json`, `servers.json`, and `instruction_files.json` are local config files (they are typically gitignored).
- Treat `llms.json` like a secret because it contains your API key.
- Rotate Azure OpenAI API keys regularly.

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

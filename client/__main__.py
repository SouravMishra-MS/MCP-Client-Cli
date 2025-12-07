import sys
import asyncio
from .mcp_client import MCPClient

async def main():
    if len(sys.argv) < 2:
        print("Usage: python -m client <server_script_path_or_url>")
        print("Examples: ")
        print("  - stdio MCP server (npm):")
        print("      python -m client @playwright/mcp@latest")
        print("  - stdio MCP server (Azure DevOps):")
        print("      python -m client @azure-devops/mcp contoso -d core work work-items")
        print("  - stdio MCP server (python):")
        print("      python -m client ./weather.py")
        print("  - SSE MCP server:")
        print("      python -m client http://localhost:3000/mcp")
        print("  - HTTP MCP server:")
        print("      python -m client http://localhost:3000/mcp")
        sys.exit(1)
    
    server = sys.argv[1]
    extra_args = sys.argv[2:]

    client = MCPClient()
    try:
        await client.connect_to_server(server, extra_args=extra_args)
        await client.chat_loop()
    finally:
        await client.cleanup()
        print("\nMCP Client closed!")


def cli_main():
    """Synchronous entry point for console script."""
    asyncio.run(main())

if __name__ == "__main__":
    cli_main()
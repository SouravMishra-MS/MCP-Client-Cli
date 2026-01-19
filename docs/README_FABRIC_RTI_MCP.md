# Microsoft Fabric RTI MCP — Quick test guide

This guide shows how to add and test the **Fabric RTI MCP** stdio server from this `mcp-client` app.

## Why this server is different

Unlike npm-based stdio servers (like `@azure-devops/mcp`), Fabric RTI MCP is typically launched with a **Python runner** (for example `uvx`).

This `mcp-client` supports that via a per-server **Command override**.

## Prerequisites

- Python + `uv` installed (so `uvx` exists)
- Network access to your Kusto cluster

Tip: verify `uvx` is available:

- `uvx --version`

## Add the server using the UI

1. Start the app (source: `python -m client`, or packaged: `mcp-client.exe`).
2. Choose **Manage MCP servers**.
3. Choose **n** (new & save).
4. Enter an alias like: `fabric-rti-mcp`
5. At `Enter MCP server path or URL`, enter:

- `microsoft-fabric-rti-mcp==0.3.0`

6. At `Command override (blank=auto)`, enter:

- `uvx`

7. At `Add extra arguments? (y/n)`, choose **y** and enter:

- `--stdio`

8. At `Add environment variables? (y/n)`, choose **y** and enter the env vars:

- `FABRIC_RTI_TRANSPORT=stdio, KUSTO_SERVICE_URI=<your-kusto-uri>, KUSTO_SERVICE_DEFAULT_DB=<your-kusto-db>`

## Example servers.json entry

After saving via the UI, you should see an entry like this in `config/servers.json`:

```json
{
  "name": "fabric-rti-mcp",
  "command": "uvx",
  "url": "microsoft-fabric-rti-mcp==0.3.0",
  "extra_args": ["--stdio"],
  "env": {
    "FABRIC_RTI_TRANSPORT": "stdio",
    "KUSTO_SERVICE_URI": "<your-kusto-uri>",
    "KUSTO_SERVICE_DEFAULT_DB": "<your-kusto-db>"
  }
}
```

## Verify it’s working

1. In **Manage MCP servers**, choose **i** (inspect capabilities).
2. Select the saved `fabric-rti-mcp` entry.
3. You should see tools listed.

If inspection fails, check `logs/mcp_client.log`.

## Notes

- Leave **Command override** blank for npm servers; this client will keep using `npx -y` automatically.
- The env var prompt supports updates and deletes:
  - Blank input keeps existing values.
  - Use `KEY=` (empty value) to remove a key.

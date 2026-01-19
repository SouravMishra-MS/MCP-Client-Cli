# Azure DevOps MCP server (ADO) — Quick test guide

This guide shows how to add and test the Azure DevOps MCP server (`@azure-devops/mcp`) using this `mcp-client` app.

## Prerequisites

- Node.js installed (so `npx` exists)
- Access to your Azure DevOps org + project

Optional (recommended for protected orgs):

- Azure CLI installed and signed in (`az login`)

## Add the server using the UI (recommended)

1. Start the app (source: `python -m client`, or packaged: `mcp-client.exe`).
2. Choose **Manage MCP servers**.
3. Choose **n** (new & save).
4. Set **Server path** to: `@azure-devops/mcp`
5. Choose **y** for extra args and enter comma-separated args.

### Minimal example (wiki domain)

Use this when your org is open to interactive auth and you want the wiki tools:

- Extra args: `contoso, -p, O365Core, -d, wiki`

### Protected orgs (recommended: Azure CLI auth)

1. Sign in:

- `az login`
- If your tenant policies require it: `az login --tenant <tenantId>`

2. Save the server with:

- Extra args: `contoso, -p, O365Core, -d, wiki, --authentication, azcli`

### Protected orgs (alternative: envvar auth)

- Extra args: `contoso, -p, O365Core, -d, wiki, --authentication, envvar`
- When prompted for environment variables, set:
  - `ADO_MCP_AUTH_TOKEN=<your-token>`

## Verify it’s working

1. In **Manage MCP servers**, choose **i** (inspect capabilities).
2. Select the saved ADO server.
3. You should see tools listed.

If tools aren’t listed or auth fails, check `logs/mcp_client.log`.

## Example servers.json entry

After saving via the UI, your entry will look like this in `config/servers.json`:

```json
{
  "name": "ADO-MCP-O365Core",
  "url": "@azure-devops/mcp",
  "extra_args": ["contoso", "-p", "O365Core", "-d", "wiki", "--authentication", "azcli"],
  "env": { "ADO_MCP_AUTH_TOKEN": "..." }
}
```

Notes:

- `env` is optional. Only include it when using `--authentication envvar`.
- The app auto-runs npm servers via `npx -y`, so you only store the package name in `url`.

## Other stdio servers (example: Fabric RTI MCP)

Some stdio MCP servers are not npm packages and must be started with a different command (for example `uvx`).
This client supports an optional per-server `command` override for those cases.

Example (similar to a VS Code config that uses `command: uvx`):

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

UI tips:

- Set `command` via the **Command override (blank=auto)** prompt when adding/editing a server.
- Leave it blank for npm-based servers like `@azure-devops/mcp` (the client will keep using `npx -y` automatically).

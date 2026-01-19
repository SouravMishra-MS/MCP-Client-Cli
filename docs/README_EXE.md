# MCP Client (.exe) Usage Guide

This guide is specifically for running the **packaged Windows executable** version of this project (built via PyInstaller).

## Where the .exe reads/writes configuration

When running as an `.exe`, this app reads and writes these files **next to the executable**:

- `config/servers.json`
- `config/llms.json`
- `instruction_files.json`
- `InstructionFiles/` (optional instruction markdown files)
- `logs/` (created automatically)

**Recommended layout** (example):

```
C:\Tools\mcp-client\
  mcp-client.exe
  config\
    servers.json
    llms.json
  instruction_files.json
  InstructionFiles\
    copilot-instructions.md
  logs\
```

If the JSON files don’t exist yet, the app will start empty and create them as you add entries in the menus.

## Prerequisites for the Azure DevOps MCP server

The Azure DevOps MCP server you referenced is an **npm package** (`@azure-devops/mcp`) that runs over stdio.

To use it from this `.exe`, you need:

- **Node.js** installed (so `npx` exists)
- Network access as required by the server

Optional (recommended for protected orgs):

- **Azure CLI** installed and signed in (for `--authentication azcli`)

Tip: confirm `npx` is available by running in PowerShell:

- `npx --version`

## Add the Azure DevOps MCP server (same as your mcp.json)

Your original `mcp.json` config:

```json
"ado": {
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "@azure-devops/mcp", "${input:ado_org}", "-p", "${input:ado_project}", "-d", "wiki"]
}
```

In this MCP Client app, you **do not** enter `npx` or `-y` manually.

- Enter the package name as the server “path”, and the rest as “extra args”.
- The client automatically launches npm-package servers using `npx -y`.

### Exact interactive steps (matching your prompts)

Go to **Manage MCP servers** and then follow:

1.

- `Options: l=list servers, n=new & save, e=edit, d=delete, i=inspect capabilities, b=back, q=quit`
- `Choose option (l):` **n**

2.

- `Name this MCP server (alias) (default):`
- Enter: **ADO-MCP-O365Core**

3.

- `Enter MCP server path or URL (https://learn.microsoft.com/api/mcp):`
- Enter: **@azure-devops/mcp**

4.

- `Add extra arguments? (y/n) (n):`
- Enter: **y**

5.

- `Enter arguments (comma-separated) ():`
- Enter (example): **contoso, -p, O365Core, -d, wiki**

6.

- `Add environment variables? (y/n) (n):`
- Enter: **n**

This produces the equivalent launch command:

- `npx -y @azure-devops/mcp contoso -p O365Core -d wiki`

### Notes about quoting / spaces

This client splits extra args using commas. If a value contains spaces, keep it wrapped in quotes as part of the argument.

Example (project name has a space):

- `contoso, -p, "O365 Core", -d, wiki`

## Verify the server works (inspect capabilities)

After saving the server:

1. In **Manage MCP servers**, choose **i** (inspect capabilities)
2. Pick your saved entry
3. The client will connect and list available Tools/Prompts/Resources

If inspection fails, check `logs/mcp_client.log`.

## Chat using the saved server

1. Choose **Chat** from the main menu
2. Choose **s** (select MCP server(s))
3. Select your `ADO-MCP-O365Core` entry

## Troubleshooting

### Protected orgs / tenant policies (authentication)

The Azure DevOps MCP server may require a specific authentication approach depending on your org’s tenant policies.

Recommended options:

1. **Azure CLI auth (often works best for protected orgs)**

- Extra args: `contoso, -p, O365Core, -d, wiki, --authentication, azcli`
- Then run `az login` (and optionally `az login --tenant <tenantId>` if needed)

2. **Env var auth**

- Extra args: `contoso, -p, O365Core, -d, wiki, --authentication, envvar`
- Env vars when saving the server: `ADO_MCP_AUTH_TOKEN=<your-token>`

3. **Interactive browser OAuth**

- Use no `--authentication` flag.
- The first time the server needs auth (typically on first tool call), it will open a browser window.

### “npx is not recognized”

Install Node.js (includes `npx`), then reopen your terminal and retry.

### The server prompts for input or hangs

This client runs npm-package servers with `npx -y` to avoid interactive prompts.

### Nothing gets saved

Make sure the `.exe` is located in a directory where it has write permissions, since it writes `servers.json`, `llms.json`, and logs beside the executable.

# 🚀 MCP-Global Bootstrap Instructions

This document allows any AI agent to install the complete MCP-Global system into a project.

## Prerequisites
- The `mcp-agentic-context` directory (containing this file) must be present in the project root.
- **Python 3.8+** installed and in PATH.
- **Git** installed (required for hooks).

## Installation

### Windows (PowerShell)
Run the automated installer. This will copy the rules to your project root, install git hooks, and build the initial index.

```powershell
# Run the installer script
powershell -ExecutionPolicy Bypass -File mcp-agentic-rules/install.ps1
```

### Linux / Mac
```bash
chmod +x mcp-agentic-rules/install.sh
./mcp-agentic-rules/install.sh
```

## Post-Install Verification
1.  **Context Check**: Run `python mcp-agentic-rules/mcp.py autocontext`.
2.  **Hooks**: Check that `.git/hooks/pre-commit` exists.
3.  **Docs**: Read `AI_AGENT_MCP.md` (generated in root) for available commands.

## System Integrity
The `mcp-agentic-context` folder contains the "Golden Copy" of the system.
- **Do not modify** files inside `mcp-agentic-context/` directly.
- The installer copies them to `mcp-agentic-rules/` in your project root.
- If you need to update the system, update `mcp-agentic-context/` and re-run the installer.

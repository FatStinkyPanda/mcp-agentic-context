# MCP Agentic Context - AI Agent Instructions

## Available Commands (50 total)

Run with: `python3 mcp-agentic-rules/mcp.py <command>`

### Before Coding
`ash
mcp autocontext              # Load relevant context
mcp recall "topic"           # Search memory
mcp search "query"           # Semantic code search
`

### While Coding
`ash
mcp predict-bugs file.py     # Check for bugs
mcp impact file.py           # What breaks?
mcp context "query"          # Get context
`

### After Coding
`ash
mcp review file.py           # Code review
mcp security file.py         # Security check
mcp test-gen file.py --impl  # Generate tests
`

### Project Packs
`ash
mcp pack list                # List available project packs
mcp pack install <pack_name> # Setup virtual environment and install pack
`

### Remember & Learn
`ash
mcp remember "key" "value"   # Store knowledge
mcp recall "query"           # Search knowledge
mcp learn --patterns         # View learned patterns
`

## Hooks (Automatic)

All hooks are installed and will run automatically:
- **pre-commit**: Auto-fix, risk check, security scan, review
- **post-commit**: Learning, index update
- **post-checkout**: Warm indexes

## Key Directories

- `mcp-agentic-rules/` - MCP package
- `.mcp/` - Index data (auto-generated)

## Quick Reference

| Need | Command |
|------|---------|
| Context | `mcp autocontext` |
| Search | `mcp search "query"` |
| Review | `mcp review .` |
| Bugs | `mcp predict-bugs .` |
| Tests | `mcp test-gen file.py` |
| Memory | `mcp remember/recall` |

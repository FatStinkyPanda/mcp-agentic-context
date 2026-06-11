# MCP Global Rules

> **AI Agent Enhancement Package** - 42 Scripts | 48 Commands | 6 Hooks

## One-Command Install

**Windows (PowerShell):**

```powershell
.\mcp-agentic-rules\install.ps1
```

**Linux/Mac:**

```bash
./mcp-agentic-rules/install.sh
```

This installs:

- All 42 Python scripts
- All 6 git hooks (enforced)
- AI agent instructions
- Initial indexes

## Quick Start

```bash
# Get help
python mcp-agentic-rules/mcp.py help

# Load AI context
python mcp-agentic-rules/mcp.py autocontext

# Search code semantically
python mcp-agentic-rules/mcp.py search "authentication"

# Predict bugs
python mcp-agentic-rules/mcp.py predict-bugs src/
```

## For AI Agents

Add `global_rules.md` to your AI agent's rules/instructions system.

## What's Included

| Category       | Commands                                                  |
| -------------- | --------------------------------------------------------- |
| **Context**    | `autocontext`, `search`, `context`, `find`                |
| **Memory**     | `remember`, `recall`, `forget`, `learn`                   |
| **Analysis**   | `review`, `security`, `profile`, `errors`, `architecture` |
| **Prediction** | `predict-bugs`, `risk-score`, `impact`, `test-gen`        |
| **Indexing**   | `index-all`, `todos`, `git-history`, `doc-index`          |
| **CI/CD**      | `github-action`, `pipeline`                               |
| **Setup**      | `setup --all`, `warm`                                     |

## Language and Scale Support

Semantic search and indexing are language-agnostic and built to scale on large
monorepos:

- **Languages**: Python, JavaScript/TypeScript (including JSX/TSX/Vue/Svelte),
  Go, Rust, Java/Kotlin, C/C++, C#, Ruby, PHP, Swift, and more.
- **Directory pruning**: ignored trees (`node_modules`, `.git`, `dist`,
  `.next`, `build`, `target`, `vendor`, ...) are pruned during the walk and
  never descended into; simple `.gitignore` directory entries are also honoured.
- **Bounded work**: minified bundles and oversized files are skipped; a full
  index is capped at `MCP_MAX_FILES` files (default 20000, set `0` for
  unlimited).
- **Deterministic offline search**: when `sentence-transformers` is not
  installed, a deterministic, identifier-aware fallback embedding is used, so
  indexed and queried vectors share the same space with no model download.

## Hooks (Auto-Enforced)

| Hook          | Actions                                |
| ------------- | -------------------------------------- |
| pre-commit    | Risk block, auto-fix, security, review |
| post-commit   | Learning, index update                 |
| post-checkout | Warm indexes                           |

## Requirements

- Python 3.8+
- Git (for hooks)

## License

MIT
<!-- Test comment for incremental indexing -->

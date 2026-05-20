# MCP Global Rules

> **AI Agent Enhancement Package** - 60+ Scripts | 70+ Commands | 6 Hooks | Auto-Learning | Bypass Detection

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
- All 60+ Python scripts
- All 6 git hooks (strictly enforced with bypass detection)
- AI agent instructions
- Initial indexes

## Quick Start

```bash
# Get help
python mcp-agentic-rules/mcp.py help

# Load 3-tier AI context (warm + skeleton + semantic)
python mcp-agentic-rules/mcp.py autocontext

# Multi-dimensional code search
python mcp-agentic-rules/mcp.py hybrid-search "authentication"

# Predict bugs
python mcp-agentic-rules/mcp.py predict-bugs src/

# Get signature-only code views (28% smaller)
python mcp-agentic-rules/mcp.py skeleton src/
```

## What's Included

| Category | Commands |
|----------|----------|
| **Context** | `autocontext`, `predict-context`, `search`, `find` |
| **Skeleton** | `skeleton`, `graph`, `call-graph`, `state` |
| **Hybrid Search** | `hybrid-search`, `correlate`, `learn-patterns` |
| **Learning** | `auto-learn`, `heal`, `lessons`, `remember`, `recall` |
| **Hooks** | `hook-guardian` |
| **Analysis** | `review`, `security`, `profile`, `errors`, `predict-bugs` |
| **Testing** | `test-gen`, `test`, `test-coverage` |
| **Management** | `index-all`, `todos`, `summarize` |

## Advanced Features

### 3-Tier Context System
```bash
mcp autocontext "task"  # Loads:
# Tier 1 (Warm): Project state + lessons learned (ALWAYS present)
# Tier 2 (Structure): Skeleton + Call graph relationships
# Tier 3 (Active): Recent files + Semantic search results
```

### Hybrid Knowledge Graph
```bash
mcp hybrid-search --build   # Build 4-dimensional graph
mcp hybrid-search "query"   # Search combining:
# - Semantic (code meaning)
# - Structural (calls/imports)
# - Temporal (access patterns)
# - Co-modification (git history)
```

### Auto-Learning System
```bash
mcp auto-learn                # View stats
mcp auto-learn --from-commit  # Extract lessons from commits
mcp auto-learn --from-test 0  # Learn from test results
mcp heal --learn "lesson"     # Add lessons manually
```

### Hook Guardian (Bypass Detection)
```bash
mcp hook-guardian          # View status
mcp hook-guardian --verify-all   # Check for bypasses
mcp hook-guardian --reconcile    # Fix bypassed commits
```

## Hooks (Strictly Enforced)

| Hook | Actions |
|------|---------|
| pre-commit | Record + fix + bugs + security + review + patterns |
| post-commit | Record + auto-learn + correlations + index + summary |
| pre-push | Verify bypasses + security + architecture |

**Bypass Detection**: Using `--no-verify` is detected and logged. Warnings on push.

## Data Files (Auto-Generated in .mcp/)

| File | Purpose |
|------|---------|
| `lessons_learned.md` | Auto-injected into every AI context |
| `project_state.json` | Goals, tasks, milestones |
| `hybrid_graph.json` | Multi-dimensional knowledge graph |
| `enhanced_learning.json` | Effectiveness scores |
| `hook_guardian.json` | Commit tracking, bypass detection |

## Requirements

- Python 3.8+
- Git (for hooks)

## License

MIT

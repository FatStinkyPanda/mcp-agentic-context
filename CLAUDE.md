# MCP AI Agent: Complete Workflow Reference

> **ENFORCED WORKFLOWS - READ AND ADHERE STRICTLY**
> This document defines the operating procedures for AI agents working on a
> project with MCP Agentic Context installed. Every command listed here
> exists in the current build; run `python mcp-agentic-rules/mcp.py help`
> for the full registry.

> **ACTIVE PRIORITY (2026-06-11, from the user): make multi-agent collab FIRST-CLASS —
> GitHub-native (issues/tasks checked out like leases) + automated impact workflows +
> 100-concurrent-agent scale (atomic fenced primitives, same-device worktree seats, E2E
> testing on every commit). The roadmap, current state, and working agreements:
> `docs/COLLAB_ROADMAP.md`. Sessions developing THIS repo join via
> `mcp collab join <callsign> --project mcp-agentic-context` (one workdir = one agent —
> seats enforce it) and keep `mcp collab selftest` AND `mcp collab swarmtest` green.
> Hooks + CI gate every commit; never bypass them.**

---

## 1. Core Principles (Non-Negotiable)

- **Fix Properly, Never Disable**: ALWAYS FIX CORRECTLY AND FULLY. Never bypass, disable, or reduce capabilities.
- **README.md as Single Source of Truth**: All decisions must align with README.md.
- **No Emojis or Icons in Code**: Prohibited unless explicitly requested.
- **Learn from Every Interaction**: Use MCP tools to record decisions, lessons, and patterns.

---

## 2. Command Execution

```bash
# Run commands from the project root:
python mcp-agentic-rules/mcp.py <command> [args]
```

Exit-code contract: 0 = success, 1 = failure. The CLI auto-bootstraps and
re-executes inside the project's .venv.

For MCP clients (Claude Code, Cursor), register the native server instead
of shelling out:

```json
{"mcpServers": {"agentic-context": {
    "command": "python",
    "args": ["mcp-agentic-rules/mcp.py", "mcp-serve"]}}}
```

---

## 3. Recommended Tool Usage

### At Session Start
| Command | Purpose |
|---------|---------|
| `mcp serve --background` | Start the warm daemon: model + index stay loaded, search answers instantly |
| `mcp autocontext [--budget N]` | Load layered context (map + memories + active files), budget-capped |
| `mcp state` | View the project goal, tasks, and notes |
| `mcp recall "topic"` | Check previous knowledge (project-scoped + global) |

### Before Making Changes
| Command | Purpose |
|---------|---------|
| `mcp search "query"` | Semantic code search by meaning (all languages) |
| `mcp skeleton src/ [--budget N]` | Signature-only view of a module or tree |
| `mcp impact <file>` | What breaks if this file changes (Python + TS/JS, pnpm-workspace aware) |

### During Development
| Command | Purpose |
|---------|---------|
| `mcp predict-bugs <file>` | Predict potential bugs |
| `mcp fix src/ --safe` | Auto-fix safe issues |
| `mcp state --add-task "..."` / `--done N` | Track increments |

### Before Committing
| Command | Purpose |
|---------|---------|
| `mcp review . --strict` | Full quality review (runs the repo's own eslint/tsc on JS/TS projects) |
| `mcp security .` | Security audit (includes pnpm audit on pnpm projects) |
| `mcp remember "lesson-key" "what was learned"` | Record lessons |

### After Changes
| Command | Purpose |
|---------|---------|
| `mcp index-all` | Refresh indexes (incremental: unchanged files cost nothing) |

---

## 4. Trigger Commands

### "dev" - Autonomous Development
1. Load context: `mcp autocontext`
2. Read README.md
3. Get tasks: `mcp state` and `mcp todos`
4. Implement autonomously
5. Commit incrementally

### "go" - Context and Suggestions
1. Load context: `mcp autocontext`
2. Read README.md
3. Identify gaps
4. **STOP** - Present suggestions, wait for direction

---

## 5. Memory System

Memories live in a user-level store shared across projects, scoped per
project so recall never leaks unrelated work:

```bash
mcp remember "auth" "src/auth/handler.ts is the entry point"   # this project
mcp remember "style" "prefer pathlib over os.path" --global    # everywhere
mcp recall "auth"                  # this project + globals
mcp recall "auth" --all-projects   # the whole store
mcp forget "auth"
```

Project state (goal/tasks/notes) lives in `.mcp/project_state.json`:

```bash
mcp state --set-goal "Implement feature X"
mcp state --add-task "Write E2E test"
mcp state --done 1
mcp state --note "API returns 204 on empty lists"
```

---

## 6. Git Hooks

`mcp setup --hooks` installs six hooks (pre-commit, post-commit,
commit-msg, pre-push, post-checkout, post-merge) that run fix/review/
security gates and keep indexes fresh. Never bypass them with
--no-verify; fix the underlying issue instead.

---

## 7. Command Reference

| Category | Commands |
|----------|----------|
| **Context** | `autocontext [--budget N]`, `context`, `search`, `find`, `skeleton`, `state` |
| **Memory** | `remember [--global]`, `recall [--all-projects]`, `forget`, `learn` |
| **Analysis** | `review`, `security`, `profile`, `errors`, `architecture`, `deps`, `predict-bugs`, `risk-score`, `impact` |
| **Quality** | `fix`, `docs`, `deadcode`, `refactor`, `migrate`, `coverage` |
| **Testing** | `test`, `test-gen`, `test-coverage` |
| **Indexing** | `index-all`, `index [--full]`, `git-history`, `todos`, `doc-index`, `config-index` |
| **Daemons** | `serve [--background/--status/--stop]`, `mcp-serve`, `watch`, `warm` |
| **Multi-Repo** | `search-all`, `repos`, `comms`, `nsync` |
| **CI/CD** | `github-action`, `pipeline` |
| **Setup** | `setup`, `doctor`, `verify`, `gui`, `pack` |

---

## 8. Data Files

| File | Purpose |
|------|---------|
| `.mcp/project_state.json` | Goal, tasks, notes (the `state` command) |
| `.mcp/vector_index/` | Semantic chunks, embeddings, per-file fingerprints |
| `.mcp/serve.json` | Warm daemon endpoint (written on start, removed on stop) |
| `.mcp/impact_graph.json` | Dependency graph for impact analysis |
| `~/.mcp/memory/knowledge.db` | Shared memory store (project-scoped rows) |

---

**System Status**: ACTIVELY MAINTAINED - docs verified against the command registry

<!-- mcp-agentic-context:start -->
## MCP Agentic Context (AI agent tooling installed in this project)

This project has semantic code search, persistent agent memory, and shared
project state. Run commands as `python mcp-agentic-rules/mcp.py <command>`
(exit codes: 0 success, 1 failure), or use the native MCP tools (server
`agentic-context` in .mcp.json) when your client supports MCP.

WHEN to reach for these tools:
- BEFORE reading files to locate code by purpose: `search "what it does"`
  (a few hundred tokens) instead of opening files to look (thousands).
- INSTEAD OF reading a whole module for its shape: `skeleton <path>`
  (signatures only, no bodies).
- AT SESSION START: `state` (shared goal/tasks/notes) and `recall "topic"`
  (memory that survives context compaction and restarts).
- IMMEDIATELY when you learn something worth keeping:
  `remember "key" "value"`.
- WHEN unsure what a change affects: `impact <file>` (Python and TS/JS,
  pnpm-workspace aware).
- ONCE per repo (then incremental and cheap): `index-all`. For instant
  searches start the warm daemon: `serve --background`. Search results
  auto-refresh after file edits.
- BEFORE committing: `review .` and `security .` (on JS/TS projects these
  run the repo's own eslint/tsc/pnpm-audit).
<!-- mcp-agentic-context:end -->

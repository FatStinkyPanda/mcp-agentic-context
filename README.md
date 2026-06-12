# MCP Agentic Context (formerly MCP Global Rules)

> **AI Agent Enhancement & Unlimited Context Package** - 75 Scripts | 76 Commands | 6 Git Hooks | Offline-First Core

[![CI](https://github.com/FatStinkyPanda/mcp-agentic-context/actions/workflows/ci.yml/badge.svg)](https://github.com/FatStinkyPanda/mcp-agentic-context/actions/workflows/ci.yml)
[![Release](https://img.shields.io/badge/release-v2.3.0-blue)](https://github.com/FatStinkyPanda/mcp-agentic-context/releases/latest)
[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)

Created by **[FatStinkyPanda](https://github.com/FatStinkyPanda)**

**Latest release: [v2.3.0](https://github.com/FatStinkyPanda/mcp-agentic-context/releases/latest)** -
the update-era release: installed copies now keep themselves current (`mcp update` — backup,
self-verify, auto-rollback; agents are notified at session start, auto-update enabled by
default), and the GitHub-native work lifecycle is complete — issues checked out with an
ATOMIC cross-machine claim, fleet self-assignment via `work next`, and landing through
auto-merged pull requests behind required CI checks. Every feature in v2.3.0 was itself
built through that lifecycle. On top of the v2.2 scale tier: 100-concurrent-agent-safe
fenced primitives proven by a per-commit multi-process swarm and a nightly 100-agent soak,
worktree seats, one-command repo provisioning — and the v2.0 line: multi-language semantic
search (25+ languages), incremental auto-fresh indexing, a warm daemon, a native Model
Context Protocol server for Claude Code/Cursor/Codex, and project-scoped memory.
Full details in the [CHANGELOG](CHANGELOG.md).

MCP Agentic Context is a drop-in AI agent enhancement system that installs into any project and gives every AI agent working on it a shared set of tools, memory, code analysis, security scanning, autonomous development workflows, and enforced quality gates. 

Equipped with **Dynamic Context Budgeting & Linguistic Zoom**, **Two-Tier Macro Codebase Dependency Graphs**, a **Preemptive Self-Healing Background Daemon**, and a **Vectorized Activity Ledger**, it is designed to grant AI agents virtually unlimited context capability and preemptive developer safeguards. It works completely offline and requires only Python 3.8+.

MCP Agentic Context began as a layer on top of [OpenMemory](https://github.com/CaviraOSS/OpenMemory)
by [CaviraOSS](https://github.com/CaviraOSS), whose local persistent memory store for LLM
applications provided the original foundation. It has expanded so far beyond that starting point -
semantic code search across 25+ languages, incremental indexing engines, code analysis and quality
gates, a warm serving daemon, a native MCP server, and autonomous development workflows - that the
codebase is practically unrecognizable from the original fork. Credit and thanks to CaviraOSS for
the foundation that started it.

Originally built to accelerate ML research and experimentation workflows, it has grown into a powerful, general-purpose tool that works equally well for any kind of software project.

---

## Staying Up To Date

Installed copies keep themselves current with the latest GitHub release:

```bash
python mcp-agentic-rules/mcp.py update --check    # newer release available? (cached 24h)
python mcp-agentic-rules/mcp.py update            # download + backup + verify + rollback-on-failure
python mcp-agentic-rules/mcp.py update --status   # versions + auto-update config
```

Session-start commands (`state`, `autocontext`, `doctor`, the `collab_status` MCP tool)
print a one-line `[UPDATE]` notice when a newer release exists — so AI agents working on
your project SEE updates where they already look. **Auto-update is enabled by default**
(opt out with `update --disable-auto`): the notice authorizes agents to apply the update
themselves. Every update backs up the current install, overlays the new release, and makes
the NEW engine pass its own 60-check selftest in a throwaway store before being accepted —
any failure rolls back automatically. Junction/symlink installs update the canonical
target, and MCP git hooks are refreshed afterwards.

---

## What Is This?

When an AI agent (Claude, Gemini, GPT-4, local LLM, etc.) works on a project with MCP Agentic Context installed, it gains access to:

- **Persistent memory** across sessions - agents remember decisions, file locations, and learned patterns
- **Semantic code search** - find related code by meaning, not just keyword
- **Automated code review** - quality checks enforced at commit time via git hooks
- **Security auditing** - scan for secrets, vulnerabilities, and injection risks before every push
- **Bug prediction** - AI-powered analysis to catch issues before they ship
- **Multi-agent collaboration, first-class** - up to 100 concurrent agents on ONE project
  (same device via worktree seats, or across machines): fenced leases, claims, a shared
  journal, GitHub issues checked out atomically and landed through gated pull requests —
  all E2E-verified on every commit by a real multi-process swarm
- **Offline-first core** - every core tool is stdlib-only and runs with no internet; optional accelerators (sentence-transformers, faiss-cpu, tree-sitter grammars, numpy, watchdog) install from PyPI and are cached for offline use afterwards

---

## Quick Install

### Windows (PowerShell)

```powershell
# From your project root:
.\mcp-agentic-rules\install.ps1 -Pack Web_Dev
```

### Linux / Mac

```bash
# From your project root:
./mcp-agentic-rules/install.sh --pack Web_Dev
```

### Manual Install

```bash
# 1. Copy mcp-agentic-rules into your project root
cp -r /path/to/mcp-agentic-rules ./mcp-agentic-rules

# 2. Initialize git if needed
git init

# 3. Install hooks manually
cp mcp-agentic-rules/.git-hooks/* .git/hooks/
chmod +x .git/hooks/*

# 4. Create data directory
mkdir -p .mcp

# 5. Wire agent discovery (CLAUDE.md + AGENTS.md sections, .mcp.json server)
python mcp-agentic-rules/mcp.py integrate

# 6. Build initial indexes
python mcp-agentic-rules/mcp.py index-all
```

### What Gets Installed

| Component | Description |
|-----------|-------------|
| `mcp-agentic-rules/` | 72 Python scripts, main entry point (`mcp.py`) |
| `.mcp/` | Index data directory (auto-generated, auto-updated) |
| `.git/hooks/pre-commit` | Blocks commits with critical issues |
| `.git/hooks/post-commit` | Updates learning and indexes |
| `.git/hooks/commit-msg` | Enriches commit context |
| `.git/hooks/pre-push` | Strict security + architecture check |
| `.git/hooks/post-checkout` | Warms context for new branch |
| `.git/hooks/post-merge` | Re-indexes after merge |
| `AI_AGENT_MCP.md` | Quick-reference for AI agents |
| `CLAUDE.md` / `AGENTS.md` sections | Marker-delimited usage triggers appended by `integrate` so Claude Code, Cursor, Codex, etc. discover the tools automatically |
| `.mcp.json` | Native MCP server registration (`agentic-context`, generated by `integrate`) |

---

## Requirements

- **Python 3.8+** (3.11+ recommended for full vendor package support)
- **Git** (for hooks and history indexing)
- No other dependencies required for core tools - the core scripts use Python stdlib only
- Optional: bundled vendor wheels in `vendor/python-packages-py311/` for enhanced analysis

---

## Command Reference (76 Commands)

Run all commands from your **project root**:

```bash
python mcp-agentic-rules/mcp.py <command> [args]
```

### Context & Search

| Command | Description |
|---------|-------------|
| `autocontext [--budget N]` | Auto-load all relevant context, hard-capped to the budget |
| `context "query"` | Get targeted context for a specific topic |
| `search "query"` | Semantic code search by meaning (uses the warm daemon when running) |
| `find "name"` | Find files and components by natural language |
| `skeleton [path] [--budget N]` | Signature-only view of files or directories |
| `state [--set-goal/--add-task/--done N/--note]` | Shared project goal, tasks, and notes |

### AI Memory

Memories are scoped to the current project by default; global memories are
visible everywhere. Legacy memories created before scoping stay global.

| Command | Description |
|---------|-------------|
| `remember "key" "value" [--global]` | Store a persistent knowledge item |
| `recall "query" [--all-projects]` | Search this project's and global memories |
| `forget "key"` | Remove a memory item |
| `learn [--patterns]` | View and reinforce learned patterns |

### Code Quality

| Command | Description |
|---------|-------------|
| `review [path] [--strict]` | Full automated code review |
| `docs [path] [--write]` | Generate or check docstrings |
| `deadcode [path]` | Find unused functions, classes, imports |
| `fix [path] [--safe] [--apply]` | Auto-fix syntax, formatting, and lint issues |
| `errors [path]` | Analyze error handling patterns |
| `coverage [path]` | Check documentation coverage (gate: >50%) |

### Analysis

| Command | Description |
|---------|-------------|
| `security [path]` | Security audit - secrets, injection, CVEs |
| `profile [path]` | Complexity and performance analysis |
| `architecture [path]` | Validate project structure |
| `deps [path]` | Dependency graph and risk analysis |
| `refactor [path]` | Suggest refactoring opportunities |
| `migrate [path]` | Detect migration issues |

### AI Prediction

| Command | Description |
|---------|-------------|
| `predict-bugs [file]` | AI-powered bug prediction |
| `risk-score` | Calculate risk score for staged changes |
| `impact [file]` | Determine what a file change will break |

### Indexing

| Command | Description |
|---------|-------------|
| `index-all` | Build all 7 indexes (semantic index is incremental: unchanged files keep their embeddings, deleted files are evicted) |
| `index [--full]` | Rebuild the semantic index; --full forces re-embedding everything |
| `git-history [file]` | Index and query git commit history |
| `todos` | List all TODO/FIXME items by priority |
| `test-coverage` | Index coverage data from pytest |
| `doc-index [path]` | Index documentation files |
| `config-index` | Index environment variables and config files |

### Testing

| Command | Description |
|---------|-------------|
| `test [path]` | Generate pytest test stubs |
| `test-gen [file] --impl` | Generate full test implementations |
| `apidocs [path]` | Generate API documentation |

### Automation

| Command | Description |
|---------|-------------|
| `watch [path]` | Live index updates on file change |
| `warm` | Pre-warm all indexes (run at session start) |
| `serve [--background/--status/--stop]` | Warm daemon: the model and index stay loaded, search answers in milliseconds |
| `mcp-serve` | Model Context Protocol server over stdio for MCP clients (Claude Code, Cursor) |
| `summarize [--output FILE]` | Generate codebase summary |
| `changelog` | Auto-generate changelog from git history |

### Multi-Agent Coordination

| Command | Description |
|---------|-------------|
| `comms status` | Check peer agent presence |
| `comms send <peer> <type> "msg"` | Send task or message to peer agent |
| `comms listen` | Poll for messages from peers |
| `comms heartbeat "status" "detail"` | Update your agent's status |
| `comms collaborate` | Enter autonomous back-and-forth loop |
| `model status` | Check current AI model assignments |
| `model switch` | Switch to next priority model |

### CI/CD

| Command | Description |
|---------|-------------|
| `github-action` | Generate GitHub Actions workflow |
| `pipeline [--gitlab]` | Generate CI/CD pipeline config |

### Project Packs

| Command | Description |
|---------|-------------|
| `pack list` | List available project packs (e.g., `ML_Wheels`, `Web_Dev`) |
| `pack install <pack_name>` | Setup a virtual environment and install pack dependencies |

### Setup

| Command | Description |
|---------|-------------|
| `setup --all` | Full setup (hooks, profile, indexes) |
| `setup --hooks` | Install git hooks only |
| `setup --profile` | Install shell profile aliases |
| `record action "..."` | Record an action to MCP log |

---

## AI Agent Trigger Commands

Two special trigger words activate predefined autonomous workflows:

### `dev` - Autonomous Development Mode

When you say **"dev"** to your AI agent, it will:

1. Find and load MCP tools automatically
2. Read `README.md` as the single source of truth
3. Run `autocontext` and `recall "project"`
4. Identify the next priority task via `todos`
5. **Implement autonomously** - no human input required
6. Commit progress incrementally, following quality gates

### `go` - Context + Suggestions Mode

When you say **"go"** to your AI agent, it will:

1. Load context and read `README.md`
2. Identify tasks and gaps via `todos`
3. **Stop and present findings** - does NOT make changes
4. List suggested next steps with priority and complexity estimates
5. Wait for your explicit direction

---

## Enforced Quality Gates

Git hooks automatically block operations that fail quality standards:

| Hook | Trigger | Blocks On |
|------|---------|-----------|
| `pre-commit` | Every commit | CRITICAL security issues, code review errors |
| `pre-push` | Every push | Doc coverage < 50%, architecture violations |
| `commit-msg` | Every commit | N/A - enriches context only |
| `post-commit` | Every commit | N/A - updates learning and indexes |
| `post-checkout` | Branch switch | N/A - warms context |
| `post-merge` | After merge | N/A - re-indexes |

---

## Mandatory AI Agent Workflow

AI agents working on MCP-enabled projects MUST follow this workflow:

### Before Making Changes

```bash
python mcp-agentic-rules/mcp.py autocontext        # Load context
python mcp-agentic-rules/mcp.py recall "topic"     # Check memory
python mcp-agentic-rules/mcp.py find "component"   # Find related files
python mcp-agentic-rules/mcp.py impact file.py     # What could break?
python mcp-agentic-rules/mcp.py predict-bugs file.py  # Bug prediction
```

### During Development

```bash
python mcp-agentic-rules/mcp.py docs src/ --write  # Add docstrings
python mcp-agentic-rules/mcp.py fix src/           # Auto-fix issues
python mcp-agentic-rules/mcp.py review src/        # Continuous review
```

### Before Committing

```bash
python mcp-agentic-rules/mcp.py review src/ --strict   # Full review
python mcp-agentic-rules/mcp.py security src/          # Security audit
python mcp-agentic-rules/mcp.py deadcode src/          # Remove unused code
python mcp-agentic-rules/mcp.py coverage src/          # Check doc coverage
```

### Before Pushing

```bash
python mcp-agentic-rules/mcp.py architecture src/            # Validate structure
python mcp-agentic-rules/mcp.py profile src/                 # Check complexity
python mcp-agentic-rules/mcp.py summarize --output SUMMARY.md  # Update context
```

### Record Decisions

```bash
python mcp-agentic-rules/mcp.py remember "auth_handler" "src/auth.py"
python mcp-agentic-rules/mcp.py record action "Implemented feature X"
python mcp-agentic-rules/mcp.py record decision "Chose approach Y because Z"
```

---

## Multi-Agent Coordination

MCP supports multiple AI agents collaborating — across machines via the `comms` system, and
**on the SAME project at the same time via `collab`** (leases + claims + journal): the
primitives that stop concurrent agent sessions from stepping on each other, battle-tested by
running multiple Claude sessions against one Unreal Engine project.

### Same-project collaboration (`collab`)

```bash
# JOIN THE TEAM in one command: binds THIS workdir to your call-sign (a SEAT),
# verifies the engine end-to-end, and prints who is doing what.
python mcp-agentic-rules/mcp.py collab join forge

# More agents on the SAME device? Provision each its own git-worktree seat:
python mcp-agentic-rules/mcp.py collab seat new ember     # ../<repo>-ember, pre-seated

# THE one view: active agents (+ workdirs), exclusive leases, claims, checked-out
# issues + conflict radar, journal tail
python mcp-agentic-rules/mcp.py collab status --project myproj --as forge

# Exclusive FENCED lease on a contended resource (an editor seat, build rights,
# the git-commit window). Atomic O_EXCL; re-entrant for the owner; STALE and even
# CORRUPT leases auto-break so a crashed session never deadlocks the team.
# Acquiring prints fence=N — before any irreversible action, prove you still hold
# THAT incarnation (a paused/zombie agent can never silently keep writing):
python mcp-agentic-rules/mcp.py collab lease acquire editor --as forge --note "verifying"
python mcp-agentic-rules/mcp.py collab lease valid editor --fence 3 --as forge
python mcp-agentic-rules/mcp.py collab lease release editor --as forge

# Advisory ownership of source areas (no conflicting authorship)
python mcp-agentic-rules/mcp.py collab claim add creatures "src/creatures/*" --as forge

# GitHub-native work checkout: the unit of work is a GitHub issue, checked out
# like a lease (gh-backed; degrades with a clear error when gh/network is absent)
python mcp-agentic-rules/mcp.py collab work list                  # open issues + who holds what
python mcp-agentic-rules/mcp.py collab work start 7 --as forge    # assign + label + claim + journal
python mcp-agentic-rules/mcp.py collab work tick 7 2 --as forge   # tick task-list checkbox 2
python mcp-agentic-rules/mcp.py collab work done 7 --pr <url>     # or close it; releases everything
python mcp-agentic-rules/mcp.py collab work drop 7 --as forge     # un-checkout without finishing

# The team radio: log what you do; tail it at EVERY loop start
python mcp-agentic-rules/mcp.py collab journal log intent --data '{"text":"refactor auth"}'
python mcp-agentic-rules/mcp.py collab journal tail 20

# Onboarding an additional agent? It runs:
python mcp-agentic-rules/mcp.py collab onboard     # prints the full join-the-team procedure
python mcp-agentic-rules/mcp.py collab selftest    # 60-check engine verification (throwaway store)

# PROVE the concurrency story: N real OS processes hammering one store —
# lease mutual exclusion, fencing under forced expiry, journal exactly-once,
# claim CAS, checkout single-winner. Runs per-push (hooks), per-commit (CI,
# 16 processes) and nightly at 100 agents.
python mcp-agentic-rules/mcp.py collab swarmtest --agents 16 --hammer
```

**The identity rule:** one working directory = one agent, bound by a seat file
(`.mcp/seat.json`) that `identity()` resolves ahead of the hostname fallback — so ten
sessions on one laptop can never silently merge into one identity. Cross-workdir use of a
seated identity is REFUSED at the lease/claim/work layer (structural enforcement, not
etiquette), and heartbeats detect both collision shapes (same identity from two workdirs;
two concurrent sessions in one workdir). The store is plain files under
`~/.mcp/nsync/.nsync_agents/collab/<project>/` — any tool can speak it, and the MCP server
exposes it as `collab_status` / `collab_lease` / `collab_journal` / `collab_message` /
`collab_claim` / `collab_work` tools. Recommended lease law for code projects: a live
tool/editor seat (its holder is the *pilot*), `rebuild`, `git-commit` (hold while
rebase+push), `bench`.

**Atomicity guarantees** (all proven by `selftest` + `swarmtest` on every commit): every
store write is an O_EXCL create, an atomic temp+rename replace, or a rename-to-unique-
tombstone take — readers never see partial JSON, exactly one contender wins any CAS, and
removals verify what they removed (restore-on-mismatch). Leases carry monotonic **fence
numbers** (Kleppmann-style) with a sidecar high-water mark, so a zombie holder that lost
its lease is structurally unable to pass `lease valid` before a destructive act. Stale
state self-heals: a janitor (elected via its own lease) reaps dead presence, orphaned
claims, abandoned checkouts, and stray temp files, bounded per pass.

**GitHub-native checkout (`collab work`):** `work start` first wins an ATOMIC cross-machine
claim — removing the issue's `state:available` label is GitHub's one-winner primitive, so
exactly one machine checks an issue out even when every agent shares one GitHub login —
then assigns the issue, labels it `in-progress` + `agent:<callsign>`, creates the matching
claim (file paths extracted from the issue body; issue URL in the note), records the
checkout in the store, and journals `work.start`. `work verify` re-confirms a checkout at
loop start / before pushing and self-drops lost ones (two machines can never finish the
same issue); `work drop` returns the label. `collab status` shows every agent's checked-out
issues, and a CONFLICT RADAR warns when two checkouts' path sets intersect. Two GitHub Actions complete the loop:
`agent-issue-impact` fires when an issue is assigned or labeled `in-progress` and posts an
auto-updated comment with the impact of the files the issue mentions (importers, transitive
dependents, affected tests — computed by this package's own `impact` engine) plus the overlap
radar against other in-progress issues; `agent-pr-impact` does the same for every PR diff.

### Cross-machine coordination (`comms`)

```bash
# 1. Check if peer is active before starting
python mcp-agentic-rules/mcp.py comms status

# 2. Announce your work
python mcp-agentic-rules/mcp.py comms heartbeat "active" "starting auth refactor"

# 3. Delegate a task to a peer
python mcp-agentic-rules/mcp.py comms send wizardpanda task "Run security scan on api/"

# 4. Listen for results
python mcp-agentic-rules/mcp.py comms listen

# 5. Enter autonomous back-and-forth loop
python mcp-agentic-rules/mcp.py comms collaborate
```

### Model Priority Enforcement

Agents MUST use models in this order:

1. **Gemini Flash** - Primary, default for all tasks
2. **Claude Opus** - Secondary, for complex reasoning
3. **Local LLM** - Fallback, zero-dependency operation

Use `python mcp-agentic-rules/mcp.py model status` to verify and `model switch` to change.

---

## NSync: Remote Execution Workflow

For tasks that need to run on a remote machine (e.g., WizardPanda / Raspberry Pi):

```bash
# Initialize a new project for remote sync
python mcp-agentic-rules/mcp.py nsync init-project my_project

# Watch for changes and sync automatically
python mcp-agentic-rules/mcp.py watch .

# Run a script on the remote machine
python mcp-agentic-rules/mcp.py nsync run my_project/main.py
```

---

## Dependency & Vendor Packages

### Core Scripts (No Installation Required)

All 53 Python scripts use **stdlib only** - Python 3.8+ standard library. Zero external dependencies for core functionality.

### Bundled Vendor Wheels (Offline-First)

Located in `vendor/python-packages-py311/` - install without internet access:

```bash
pip install --no-index --find-links=vendor/python-packages-py311 pylint flake8 black mypy bandit pytest
```

Key bundled packages:

| Category | Packages |
|----------|----------|
| **Code Quality** | pylint 4.0.4, flake8 7.3.0, black 25.12.0, isort 7.0.0, mypy 1.19.1 |
| **Security** | bandit 1.9.2, safety 3.7.0, pip-audit 2.10.0 |
| **Testing** | pytest 9.0.2, pytest-cov 7.0.0, coverage 7.13.1 |
| **Analysis** | radon 6.0.1, astroid 4.0.2 |
| **Utilities** | rich 14.2.0, pydantic 2.12.5, requests 2.32.5, cryptography 46.0.3 |

---

## Project Structure

```
mcp-agentic-context/          # This repository
├── README.md                 # You are here
├── CLAUDE.md / AGENTS.md     # Agent workflow guidance (auto-discovered)
├── AI_AGENT_MCP.md           # Quick reference for AI agents
├── .mcp.json                 # Native MCP server registration
├── .github/workflows/ci.yml  # Lint + test suite on Linux and Windows
├── docs/                     # Design notes and setup guides
├── project_packs/            # Optional per-domain environment packs
└── mcp-agentic-rules/        # THE package - copy this into projects
```

The package itself:

```
mcp-agentic-rules/
├── mcp.py                    # Main entry point (run this)
├── install.ps1               # Windows one-command installer
├── install.sh                # Linux/Mac one-command installer
├── global_rules.md           # Full AI agent rules (add to agent instructions)
├── AI_AGENT_INSTRUCTIONS.md  # Concise enforced workflow reference
├── DEPENDENCIES.md           # Full dependency documentation
├── scripts/                  # 72 Python tool modules
│   ├── autocontext.py        # Context auto-loader
│   ├── memory.py             # Persistent AI memory
│   ├── review.py             # Code review automation
│   ├── security.py           # Security auditing
│   ├── predict.py            # Bug prediction
│   ├── impact.py             # Change impact analysis
│   ├── vector_store.py       # Semantic search embeddings
│   ├── agent_comms.py        # Multi-agent coordination
│   ├── nsync.py              # Remote sync and execution
│   ├── auto_test.py          # Test generation
│   ├── index_all.py          # Full index rebuild
│   ├── serve.py              # Warm daemon (instant search/recall)
│   ├── mcp_server.py         # Model Context Protocol server (stdio)
│   ├── skeleton.py           # Signature-only views
│   ├── project_state.py      # Shared goals/tasks/notes
│   ├── js_toolchain.py       # eslint/tsc/pnpm-audit bridge
│   ├── call_graph.py         # Call graph relationships
│   ├── hybrid_graph.py       # Multi-dimensional knowledge graph
│   ├── predict_context.py    # Task-based context prediction
│   ├── auto_heal.py          # Error analysis and lessons learned
│   └── ...                   # 52 more tools
├── .git-hooks/               # 6 enforceable git hooks
│   ├── pre-commit
│   ├── post-commit
│   ├── commit-msg
│   ├── pre-push
│   ├── post-checkout
│   └── post-merge
├── vendor/                   # Optional offline packages
│   ├── python-packages-py311/  # Place wheels here for air-gapped installs (not bundled)
│   └── mcp-servers/            # MCP server configs
└── config/                   # Configuration templates
```

---

## Core Principles

These principles are enforced by the system and must be followed by all agents:

1. **Fix Properly, Never Disable** - Always fix issues completely. Never restrict, disable, or reduce capabilities. All integrations must build on what already exists.

2. **README as Single Source of Truth** - `README.md` defines project goals and roadmap. All agent decisions must align with it.

3. **No Emojis in Code** - Emojis in source code cause encoding errors across devices and platforms. Prohibited unless explicitly requested.

4. **Autonomous Collaboration** - Agents must coordinate via `mcp comms` to avoid conflicts. Zero human intervention is the goal.

5. **Model Priority Enforcement** - Gemini Flash first, Claude Opus second, local LLM as fallback. Switch automatically on rate limits.

---

## About the Author

MCP Agentic Context was created by **[FatStinkyPanda](https://github.com/FatStinkyPanda)**, a machine learning engineer specializing in:

- Designing and training research AI models using **PyTorch** and (occasionally) **TensorFlow**
- Building entire **AI model architectures from scratch** - transformers, custom attention mechanisms, novel training paradigms
- End-to-end ML research pipelines, from dataset curation through training, evaluation, and deployment

This project was born out of a need to move faster across many parallel research experiments. Managing code quality, context, memory, and agent coordination by hand across dozens of experimental branches was a constant bottleneck. MCP Agentic Context was built to eliminate that overhead entirely - starting from the foundation laid by [CaviraOSS's OpenMemory](https://github.com/CaviraOSS/OpenMemory) and growing into the system it is today.

While it was designed with ML research workflows in mind, the system is completely general-purpose and has proven equally effective for web development, systems programming, data engineering, and any other project where AI agents are part of the development process.

> If you find this useful, give it a star and check out my other work at [github.com/FatStinkyPanda](https://github.com/FatStinkyPanda).

---

## License

[Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE)

---

## Contributing

1. Fork the repository
2. Run `python mcp-agentic-rules/mcp.py index-all` to build indexes
3. Make your changes following the mandatory workflow above
4. Ensure `python mcp-agentic-rules/mcp.py review .` and `security .` pass clean
5. Open a pull request with a clear description of what changed and why

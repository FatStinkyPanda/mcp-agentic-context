# Changelog

## v2.1.0 (2026-06-11)

- NEW `collab` command: same-project multi-agent coordination — exclusive TTL'd
  LEASES (atomic acquire, re-entrant, stale auto-break: a crashed session never
  deadlocks the team; `--wait` polls until free), advisory CLAIMS on source
  areas, an append-only per-project JOURNAL (the team radio, auto-rotated at
  2 MB), `status` one-view, `onboard` (prints the complete join-the-team
  procedure for an additional agent), `selftest` (6-check engine verification).
- IDENTITY-COLLISION detection: presence heartbeats carry the working
  directory; two live sessions beating one identity from different dirs warn
  loudly and journal `identity.collision` (the rule: one workdir = one agent;
  use `git worktree` per agent). Battle-tested by concurrent Claude sessions
  on one Unreal Engine project — the collision class this catches caused a
  real six-fixture test cascade before detection existed.
- MCP server exposes the engine to any client: `collab_status` (+onboard),
  `collab_lease`, `collab_journal`, `collab_message`, `collab_claim`.
- The store file format (~/.mcp/nsync/.nsync_agents/collab/<project>/) is a
  documented contract: zero-dependency per-project clients can speak it
  directly (first consumer: the AI_Gen UE project, which enforces the editor
  lease inside its bridge layer).

## v2.0.2 (2026-06-11)

- review and security accept single-file paths (previously scanned 0
  files and reported PASSED); a lone JS/TS file resolves its owning
  project via the nearest package.json and eslint targets just that file
- autocontext code fences derive their language from the file extension
  instead of always claiming python
- autocontext caps each memory value at 400 chars in its memory layer so
  one verbose entry (e.g. a legacy auto-snapshot) cannot consume the
  whole memory budget; legacy pre-scoping snapshot pollution in shared
  stores should be purged (see scripts/clean-snapshot-memories.py pattern)

## v2.0.1 (2026-06-10)

- MCP server: four new tools join the native set - impact (what breaks if
  this file changes), review and security (pre-commit/pre-push gates
  returning structured reports, using the repo's own toolchain on JS/TS),
  and todos (priority-ordered TODO/FIXME listing). All tool outputs are
  capped so a pathological report cannot flood agent context. Ten tools
  total, ~1.1k tokens of schemas per session.

## v2.0.0 (2026-06-10)

Large-codebase readiness, agent-native integration, and a first-class
repository layout. 125 tests, CI on Linux and Windows.

### Multi-language and scale
- Semantic indexing and search cover TypeScript/TSX/JS and 25+ languages
  (previously Python-only; a TS monorepo indexed zero files)
- File discovery prunes node_modules/.git/dist/.next/build trees, honors
  .gitignore, skips minified/generated files, and caps pathological scans
  (MCP_MAX_FILES)
- Incremental re-indexing with per-file fingerprints: unchanged files keep
  their embeddings, deleted files are evicted; a no-change re-index of a
  32,000-file repo takes 0.3s
- Auto-fresh search: the index reconciles with the file system before every
  search, so results are never stale after edits
- Deterministic fallback embeddings (previously per-process hash salting
  made cross-process search results meaningless)
- impact resolves TS/JS imports including pnpm workspace packages

### Agent-native integration
- mcp-serve: a real Model Context Protocol server over stdio exposing
  semantic_search, recall_memory, remember, autocontext, skeleton, and
  project_state as native MCP tools, with when-to-use steering in every
  description
- serve: persistent warm daemon; searches answer in ~0.4s instead of
  paying a multi-second model load per call
- integrate: installs are self-advertising (marker-delimited sections in
  CLAUDE.md and AGENTS.md, generated/merged .mcp.json registration);
  called automatically by both installers
- autocontext --budget with a hard output cap; skeleton command for
  signature-only views; state command for shared goals/tasks/notes
- Memory is project-scoped by default (--all-projects, remember --global)

### Restored intelligence layer
- Salvaged from an orphaned duplicate tree and registered: heal, graph/
  call-graph, hybrid-search/hybrid, predict-context, learn-patterns/
  correlate, hook-guardian, plus the enhanced auto_learn

### Quality on JS/TS projects
- review runs the repo's own eslint and tsc; security runs pnpm audit

### Correctness and robustness
- Exit-code contract: 0 success, 1 failure; closed-pipe and Ctrl-C exits
  are clean; console output is codepage-safe on Windows
- Project-root detection knows JS/monorepo markers and can never resolve
  to the user home directory (the global ~/.mcp store no longer counts
  as a project marker)
- Multi-verb CLI dispatch fixed: "mcp search" returned nothing and
  "mcp forget" performed a recall
- TypeScript tree-sitter grammars load (language_typescript resolution)
- heavy sentence-transformers import is lazy
- heal fails fast on silent stdin instead of hanging agents
- Six latent crash bugs fixed (missing Tuple/Dict/subprocess imports)
- Windows installer detects a WORKING Python (the Microsoft Store
  python3 stub no longer breaks installs)

### Repository
- Flattened layout: the divergent nested package duplicate is gone, CI
  promoted to the repo root and fixed, shipped git hooks repaired (they
  invoked the nested path and were broken for canonical installs), design
  docs under docs/, all hardcoded personal paths removed
- Documentation aligned with the real command set (72 scripts, 76
  commands; removed claims of bundled wheels that were never shipped)

## v1.0.0

Initial rebranded release of mcp-agentic-context (formerly MCP Global
Rules).

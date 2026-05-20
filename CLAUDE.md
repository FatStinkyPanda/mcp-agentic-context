# MCP AI Agent: Complete Workflow Reference

> **ENFORCED WORKFLOWS - READ AND ADHERE STRICTLY**
> This document defines the MANDATORY operating procedures for all AI agents. Integrates MCP-Global with auto-learning, bypass detection, and strict enforcement.

---

## 1. Core Principles (Non-Negotiable)

- **Fix Properly, Never Disable**: ALWAYS FIX CORRECTLY AND FULLY. Never bypass, disable, or reduce capabilities.
- **README.md as Single Source of Truth**: All decisions must align with README.md.
- **No Emojis or Icons in Code**: Prohibited unless explicitly requested.
- **Learn from Every Interaction**: Use MCP tools to record decisions, lessons, and patterns.

---

## 2. Command Execution

```bash
# Find MCP
MCP=$(find . -name "mcp.py" -path "*/mcp-agentic-rules/*" | head -1)

# Run commands
python $MCP <command>
```

---

## 3. Mandatory Tool Usage

### Before Making Changes
| Command | Purpose |
|---------|---------|
| `mcp autocontext` | Load 3-tier context (warm+skeleton+semantic) |
| `mcp predict-context "task"` | Pre-bundle predicted files for task |
| `mcp hybrid-search "query"` | Multi-dimensional search |
| `mcp graph "function"` | Query call graph relationships |
| `mcp state` | View project goals and lessons |
| `mcp recall "topic"` | Check previous knowledge |

### During Development
| Command | Purpose |
|---------|---------|
| `mcp skeleton src/` | Get compressed signature-only views |
| `mcp predict-bugs file.py` | Predict potential bugs |
| `mcp heal "error"` | Get fix suggestions for errors |
| `mcp fix src/ --safe` | Auto-fix safe issues |

### Before Committing
| Command | Purpose |
|---------|---------|
| `mcp review . --strict` | Full quality review |
| `mcp security .` | Security audit |
| `mcp heal --learn "lesson"` | Record lessons learned |

### After Committing (Automatic via Hooks)
- `mcp auto-learn --from-commit` - Extract lessons
- `mcp learn-patterns` - Update correlations
- `mcp hook-guardian --record-commit` - Track for bypass detection

---

## 4. Trigger Commands

### "dev" - Autonomous Development
1. Load context: `mcp autocontext`
2. Read README.md
3. Get tasks: `mcp todos`
4. Implement autonomously
5. Commit incrementally

### "go" - Context and Suggestions
1. Load context: `mcp autocontext`
2. Read README.md
3. Identify gaps
4. **STOP** - Present suggestions, wait for direction

---

## 5. Learning System

MCP learns automatically from:

| Source | What It Learns | Trigger |
|--------|----------------|---------|
| Commits | Lessons from messages | `auto-learn --from-commit` |
| Tests | Success/failure patterns | `auto-learn --from-test` |
| Access | File sequences (A→B→C) | Automatic |
| Git | Co-modification patterns | `learn-patterns` |

### Recording Lessons
```bash
mcp heal --learn "Use pathlib instead of os.path"
mcp remember "auth" "src/auth/handler.py"
mcp state --set-goal "Implement feature X"
```

---

## 6. Hook Enforcement

**All hooks are strictly enforced with bypass detection:**

| Hook | Actions |
|------|---------|
| pre-commit | Record flag + fix + bugs + security + review |
| post-commit | Record commit + auto-learn + correlations + index |
| pre-push | Verify no bypasses + security + architecture |

**Bypass Detection**: Using `--no-verify` is logged. Warnings on push.

```bash
mcp hook-guardian          # View bypass status
mcp hook-guardian --verify-all   # Check for bypasses
mcp hook-guardian --reconcile    # Run skipped checks
```

---

## 7. Command Reference (60+ Commands)

| Category | Commands |
|----------|----------|
| **Context** | `autocontext`, `predict-context`, `context`, `search`, `find` |
| **Skeleton** | `skeleton`, `graph`, `call-graph`, `state`, `project-state` |
| **Hybrid** | `hybrid-search`, `hybrid`, `correlate`, `learn-patterns` |
| **Learning** | `auto-learn`, `heal`, `lessons`, `remember`, `recall` |
| **Hooks** | `hook-guardian` |
| **Analysis** | `review`, `security`, `profile`, `errors`, `predict-bugs` |
| **Testing** | `test-gen`, `test`, `test-coverage` |
| **Management** | `index-all`, `todos`, `summarize` |

---

## 8. Data Files

| File | Purpose |
|------|---------|
| `.mcp/lessons_learned.md` | Auto-injected into every context |
| `.mcp/project_state.json` | Goals, tasks, milestones |
| `.mcp/hybrid_graph.json` | Multi-dimensional knowledge graph |
| `.mcp/enhanced_learning.json` | Effectiveness scores, patterns |
| `.mcp/hook_guardian.json` | Commit tracking, bypass detection |

---

**System Status**: STRICTLY ENFORCED

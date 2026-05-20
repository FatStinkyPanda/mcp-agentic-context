# MCP AI Agent Instructions - ENFORCED WORKFLOWS

## Overview

This document defines **mandatory workflows** for AI agents working with MCP-enabled projects. Workflows are **automatically enforced** via git hooks with **bypass detection**.

## Required Tool Usage

### Before Making Changes - Context Loading
```bash
python mcp.py autocontext             # Load 3-tier context (warm+skeleton+semantic)
python mcp.py predict-context "task"  # Pre-bundle files for your task
python mcp.py hybrid-search "query"   # Multi-dimensional code search
python mcp.py skeleton src/           # Get signature-only views (28% smaller)
python mcp.py graph "function"        # Query call graph relationships
python mcp.py state                   # View project goals/tasks/lessons
```

### During Development
```bash
python mcp.py predict-bugs file.py    # Predict bugs before they happen
python mcp.py heal "error message"    # Get fix suggestions for errors
python mcp.py fix src/ --safe         # Auto-fix safe issues
python mcp.py review src/             # Check quality continuously
```

### Before Committing
```bash
python mcp.py review src/ --strict    # Full quality review
python mcp.py security src/           # Security audit
python mcp.py heal --learn "lesson"   # Record lessons learned
```

### Automatic (via Hooks)
```bash
# pre-commit: Records flag + fix + bugs + security + review + patterns
# post-commit: Records commit + auto-learn + correlations + index
# pre-push: Verifies bypasses + security + architecture
```

## Hook Enforcement (Strict)

| Hook | Actions | Blocking |
|------|---------|----------|
| pre-commit | fix, predict-bugs, security, review, patterns | Yes |
| post-commit | auto-learn, correlations, index, summarize | No |
| pre-push | verify-bypasses, security, architecture | Yes |

**Bypass Detection**: Using `--no-verify` is logged. Warnings shown on push.

```bash
mcp hook-guardian              # View bypass status
mcp hook-guardian --verify-all # Check for bypassed commits
mcp hook-guardian --reconcile  # Run skipped checks
```

## Learning System

MCP learns automatically from every interaction:

| Source | Command | What It Learns |
|--------|---------|----------------|
| Commits | `auto-learn --from-commit` | Lessons from messages |
| Tests | `auto-learn --from-test 0` | Success/failure patterns |
| Access | Automatic | File sequences (A→B→C) |
| Git | `learn-patterns` | Co-modification patterns |

### Recording Knowledge
```bash
mcp heal --learn "Use pathlib instead of os.path"
mcp remember "auth" "src/auth/handler.py"
mcp state --set-goal "Complete authentication"
```

## Tool Quick Reference

| Need | Command |
|------|---------|
| **Load context** | `mcp autocontext` |
| **Predict files** | `mcp predict-context "task"` |
| **Multi-dim search** | `mcp hybrid-search "query"` |
| **Code skeletons** | `mcp skeleton src/` |
| **Call graph** | `mcp graph "function"` |
| **Project state** | `mcp state` |
| **Predict bugs** | `mcp predict-bugs .` |
| **Error help** | `mcp heal "error"` |
| **Add lesson** | `mcp heal --learn "lesson"` |
| **Check bypasses** | `mcp hook-guardian` |
| **File correlations** | `mcp correlate` |

## Advanced Commands

| Category | Commands |
|----------|----------|
| **Context** | `autocontext`, `predict-context`, `search`, `find` |
| **Skeleton** | `skeleton`, `graph`, `call-graph`, `state` |
| **Hybrid** | `hybrid-search`, `correlate`, `learn-patterns` |
| **Learning** | `auto-learn`, `heal`, `lessons` |
| **Hooks** | `hook-guardian` |
| **Analysis** | `review`, `security`, `predict-bugs`, `profile` |

## Workflow Example

```bash
# 1. Load context and predict needed files
mcp autocontext
mcp predict-context "add user authentication"

# 2. Understand codebase structure
mcp skeleton src/auth/
mcp graph "login"

# 3. Make changes with continuous checks
mcp predict-bugs .
mcp review . --staged

# 4. Record lessons and commit
mcp heal --learn "Always hash passwords with bcrypt"
git commit -m "feat: add user authentication"

# 5. Verify and push (hooks run automatically)
git push  # Hook guardian verifies no bypasses
```

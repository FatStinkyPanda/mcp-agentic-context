#!/usr/bin/env python3
"""
MCP Tools Runner
================
Single entry point for all MCP AI enhancement tools.

Works correctly regardless of:
- How it's invoked (relative path, absolute path, symlink)
- Current working directory
- Installation location in project
"""

from pathlib import Path
import json
import os
import sys

import importlib

# =============================================================================
# CRITICAL: Resolve the ACTUAL location of this script
# =============================================================================

def get_package_root():
    """
    Get the absolute path to the core package directory.
    Handles symlinks, relative paths, and various invocation methods.
    """
    # Method 1: Use __file__ (works in most cases)
    if '__file__' in dir():
        script_path = Path(__file__).resolve()
        return script_path.parent

    # Method 2: Use sys.argv[0] (when __file__ isn't available)
    if sys.argv:
        script_path = Path(sys.argv[0]).resolve()
        if script_path.name == 'mcp.py':
            return script_path.parent

    # Method 3: Search common locations
    cwd = Path.cwd()

    # Check if package rules folder is in current directory
    for pkg_name in ('mcp-agentic-rules', 'mcp-agentic-rules'):
        if (cwd / pkg_name / 'mcp.py').exists():
            return cwd / pkg_name

    # Check if we're inside the package folder
    if (cwd / 'mcp.py').exists() and (cwd / 'scripts').exists():
        return cwd

    # Check parent directories
    for parent in cwd.parents:
        for pkg_name in ('mcp-agentic-rules', 'mcp-agentic-rules'):
            if (parent / pkg_name / 'mcp.py').exists():
                return parent / pkg_name

    return None


# Get MCP root and add to path
MCP_ROOT = get_package_root()

if MCP_ROOT is None:
    print("[FAIL] Cannot find mcp core package directory")
    print("Make sure you're running from a project with the package rules installed")
    sys.exit(1)


def ensure_venv_execution():
    """
    Ensures that this script is executed inside the project's virtual environment (.venv).
    If it is not, it locates the venv Python executable and re-executes itself.
    """
    # Don't auto-execute if they are trying to setup/doctor/gui outside venv or if it's already in venv
    in_venv = (
        hasattr(sys, 'real_prefix') or
        (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    )
    if in_venv:
        return

    # Check if we should bypass auto-venv for setup commands
    bypass_cmds = ('setup', 'doctor', 'verify', 'gui', 'pack', 'integrate')
    if len(sys.argv) > 1 and sys.argv[1] in bypass_cmds:
        return

    project_root = MCP_ROOT.parent
    venv_path = project_root / ".venv"

    # Check if .venv python executable exists
    if os.name == 'nt':
        venv_python = venv_path / "Scripts" / "python.exe"
    else:
        venv_python = venv_path / "bin" / "python"

    if venv_python.exists():
        import subprocess
        cmd = [str(venv_python), str(MCP_ROOT / "mcp.py")] + sys.argv[1:]
        sys.exit(subprocess.call(cmd))
    else:
        # Auto-bootstrap virtual environment
        print("[MCP VENV] Virtual environment not found. Bootstrapping...")
        try:
            if str(MCP_ROOT) not in sys.path:
                sys.path.insert(0, str(MCP_ROOT))
            from scripts.venv_manager import VenvManager
            vm = VenvManager(str(project_root))
            if vm.ensure_venv():
                import subprocess
                cmd = [str(venv_python), str(MCP_ROOT / "mcp.py")] + sys.argv[1:]
                sys.exit(subprocess.call(cmd))
        except Exception as e:
            print(f"[MCP VENV ERROR] Could not bootstrap virtual environment: {e}")


# Run virtual environment enforcement
ensure_venv_execution()

# Add MCP root to path for imports
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

# Store for other modules to use
os.environ['MCP_ROOT'] = str(MCP_ROOT)

# Make console output resilient on Windows legacy codepages: indexed source
# files may contain characters the active console codepage cannot encode, and
# a print() must never crash a command over a lone glyph.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass


def show_help():
    """Show help message."""
    print("""
MCP AI Enhancement Tools (48 Commands)
=======================================

Usage: python3 mcp-agentic-rules/mcp.py <command> [args...]

Code Quality:
    review [path] [--strict]    Code review automation
    docs [path] [--write]       Generate missing docstrings
    test [path]                 Generate pytest test stubs
    deadcode [path]             Find unused code
    fix [path] [--safe --apply] Auto-fix issues

Analysis:
    deps [path]                 Dependency analysis
    profile [path]              Performance/complexity
    security [path]             Security audit
    errors [path]               Error handling
    architecture [path]         Architecture validation

Intelligence:
    context "query" [path]      Smart context extraction
    find "query" [path]         Natural language search
    skeleton [path] [--budget N] Signature-only view of files/dirs
    state [--set-goal/--add-task/--done N/--note] Project goals and tasks
    refactor [path]             Suggest refactorings
    heal "error" [--learn/--lessons] Fix suggestions and lessons learned
    graph build|"function"      Call graph relationships
    predict-context "task"      Pre-bundle predicted files for a task
    hybrid-search "query"       Multi-dimensional knowledge graph search
    learn-patterns              Update co-modification correlations
    hook-guardian [--verify-all] Commit tracking and bypass detection

Indexes:
    index-all                   Full reindex (all 7)
    git-history [file]          Git commit history
    todos                       List TODOs/FIXMEs
    impact [file]               What breaks?
    test-coverage               Coverage data

AI Memory:
    remember "key" "value"      Store knowledge
    recall "query"              Search memories
    forget "key"                Remove memory
    learn [--patterns]          Learn from feedback

AI Prediction:
    predict-bugs [file]         Predict bugs
    risk-score                  Change risk score
    test-gen [file] --impl      Generate full tests

Multi-Repo:
    search-all "query"          Search all projects
    repos --add [path]          Manage repos

CI/CD:
    github-action               Generate workflow
    pipeline [--gitlab]         Generate pipeline

Multi-Agent Collaboration:
    collab status               Agents + leases + claims + work + journal in one view
    collab lease acquire <res>  Exclusive TTL'd lease (editor/build/git-commit/...)
    collab lease release|renew|break|status <res>
    collab claim add <id> <pattern>  Advisory work-area ownership
    collab work list            Open GitHub issues + who has them checked out
    collab work start <issue#> [--branch]   Check OUT an issue (assign+label+claim+journal)
    collab work done <issue#> [--pr URL] | drop <issue#> | tick <issue#> <item#>
    collab journal log <event> [--data JSON] | tail [N]
    comms status|send|listen    Presence + agent-to-agent messages

Automation:
    watch [path]                Live index updates
    autocontext [--budget N]    Auto-load context
    warm                        Pre-warm indexes
    serve [--background/--status/--stop] Warm daemon: instant search/recall
    mcp-serve                   Model Context Protocol server over stdio

Setup & Diagnostics:
    setup --all                 Full setup
    setup --hooks               Install git hooks
    integrate                   Wire agent discovery (CLAUDE.md/AGENTS.md/.mcp.json)
    doctor                      Run system health diagnostics (self-repair)
    gui                         Launch interactive local web GUI dashboard
    record action "..."         Record an action to MCP log

Project Packs:
    pack list                   List available project packs
    pack install <name>         Install a project pack
""")


# Map commands to modules
COMMANDS = {
    # Original tools
    'test': 'auto_test',
    'docs': 'auto_docs',
    'deadcode': 'dead_code',
    'deps': 'deps',
    'summarize': 'summarize',
    'changelog': 'changelog',
    'review': 'review',
    # Phase 2 tools
    'context': 'context',
    'refactor': 'refactor',
    'apidocs': 'api_docs',
    'coverage': 'doc_coverage',
    'security': 'security',
    'profile': 'profile',
    "rem": "reminder",
    "rec": "record",
    "cybersec": "cybersec",
    "nsync": "nsync",
    "comms": "agent_comms",
    "collab": "agent_collab",
    "model": "model_manager",
    'find': 'finder',
    'errors': 'errors',
    'migrate': 'migrate',
    'architecture': 'architecture',
    'arch': 'architecture',
    'fix': 'fix',
    'record': 'record',
    'trigger-loop': 'trigger_loop',
    # Semantic
    'index': 'vector_store',
    'search': 'vector_store',
    'skeleton': 'skeleton',
    'state': 'project_state',
    'project-state': 'project_state',
    # Deep-context intelligence (restored from the legacy dev tree)
    'heal': 'auto_heal',
    'graph': 'call_graph',
    'call-graph': 'call_graph',
    'correlate': 'correlation_tracker',
    'learn-patterns': 'correlation_tracker',
    'hook-guardian': 'hook_guardian',
    'hybrid-search': 'hybrid_graph',
    'hybrid': 'hybrid_graph',
    'predict-context': 'predict_context',
    'pattern': 'astgrep',
    'parse': 'treesitter_utils',
    'embed': 'embeddings',
    # Automation
    'watch': 'watcher',
    'autocontext': 'autocontext',
    'auto': 'autocontext',
    'serve': 'serve',
    'mcp-serve': 'mcp_server',
    # Advanced indexes
    'index-all': 'index_all',
    'git-history': 'git_index',
    'blame': 'git_index',
    'todos': 'todo_index',
    'impact': 'impact',
    'test-coverage': 'coverage_index',
    'doc-index': 'doc_index',
    'config-index': 'config_index',
    # AI Enhancements
    'remember': 'memory',
    'recall': 'memory',
    'forget': 'memory',
    'learn': 'learning',
    'predict-bugs': 'predict',
    'risk-score': 'predict',
    'search-all': 'multi_repo',
    'repos': 'multi_repo',
    'github-action': 'cicd',
    'pipeline': 'cicd',
    'test-gen': 'test_gen',
    # Setup & Automation
    'setup': 'setup',
    'integrate': 'integrate',
    'warm': 'warm',
    'auto-learn': 'auto_learn',
    # Project Packs
    'pack': 'pack_manager',
    # Health & GUI
    'doctor': 'doctor',
    'verify': 'doctor',
    'gui': 'gui',
}


def main():
    """Main entry point."""
    workspace = None
    argv = list(sys.argv)
    
    # Extract --workspace or -w from sys.argv
    for opt in ('--workspace', '-w'):
        if opt in argv:
            idx = argv.index(opt)
            if idx + 1 < len(argv):
                workspace = argv[idx + 1]
                del argv[idx:idx+2]
            else:
                del argv[idx]

    if workspace:
        os.environ['MCP_WORKSPACE'] = workspace

    if len(argv) < 2 or argv[1] in ('help', '-h', '--help'):
        show_help()
        return 0

    command = argv[1]
    args = argv[2:]

    if command not in COMMANDS:
        print(f"[FAIL] Unknown command: {command}")
        show_help()
        return 1

    module_name = COMMANDS[command]

    # Expose the invoked command name so multi-verb modules (several commands
    # mapping to one module, e.g. index/search -> vector_store) can tell which
    # verb was requested. sys.argv only carries the verb's arguments.
    os.environ['MCP_COMMAND'] = command

    try:
        # Import the module
        module = importlib.import_module(f'scripts.{module_name}')

        # Update sys.argv for the module
        sys.argv = [f'scripts/{module_name}.py'] + args

        if hasattr(module, 'main'):
            # Exit-code contract: 0 = success, 1 = failure. Normalize whatever
            # a module returns (None, bools, negative ints that would wrap to
            # 255 on Windows) onto that contract.
            rc = module.main()
            return 0 if rc is None or rc == 0 else 1
        else:
            print(f"[FAIL] Module {module_name} has no main function")
            return 1

    except ImportError as e:
        print(f"[FAIL] Could not import {module_name}: {e}")
        print(f"MCP_ROOT: {MCP_ROOT}")
        print(f"sys.path: {sys.path[:3]}")
        return 1
    except Exception as e:
        print(f"[FAIL] Error running {command}: {e}")
        import traceback
        traceback.print_exc()
        return 1


def _exit_for_closed_pipe():
    """
    Exit 0 when the reader closed the pipe early (piping into head etc.).
    Point stdout at devnull first so the interpreter's final flush cannot
    fail again and turn a non-error into exit code -1/255.
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    try:
        rc = main()
        # Flush inside the handler scope: on Windows a closed pipe surfaces
        # here as OSError(EINVAL) rather than BrokenPipeError.
        sys.stdout.flush()
        sys.exit(rc)
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        _exit_for_closed_pipe()
    except OSError as e:
        if e.errno in (22, 32):  # EINVAL / EPIPE: closed pipe on Windows
            _exit_for_closed_pipe()
        raise

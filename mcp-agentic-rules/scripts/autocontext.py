"""
Auto-Context Loader
===================
Automatically load relevant code context for AI agents.

Usage:
    python mcp.py context --auto      # Get auto-loaded context
    python mcp.py context --recent    # Context from recent files
"""

from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import os
import sys
import ast

from .utils import Console, find_project_root
from .dynamic_context import ContextBudgetEngine, skeletonize_file
from .dependency_graph import MacroCodebaseGraph


@dataclass
class ContextCache:
    """Cache of context state."""
    recent_files: List[str] = field(default_factory=list)
    hot_files: Dict[str, int] = field(default_factory=dict)  # path -> access count
    last_query: str = ""
    last_task: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'ContextCache':
        return cls(**data)


@dataclass
class ContextResult:
    """Result of context loading."""
    files: List[Tuple[str, str]]  # (path, content summary)
    token_count: int
    source: str  # 'recent', 'semantic', 'dependency'


def get_cache_path(root: Path = None) -> Path:
    """Get path to context cache."""
    root = root or find_project_root() or Path.cwd()
    return root / '.mcp' / 'memory' / 'context_cache.json'


def load_cache(root: Path = None) -> ContextCache:
    """Load context cache from disk."""
    cache_path = get_cache_path(root)

    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return ContextCache.from_dict(data)
        except Exception:
            pass

    return ContextCache()


def save_cache(cache: ContextCache, root: Path = None):
    """Save context cache to disk."""
    cache_path = get_cache_path(root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    cache.timestamp = datetime.utcnow().isoformat() + 'Z'

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cache.to_dict(), f, indent=2)


def track_file_access(path: Path, root: Path = None):
    """Track that a file was accessed."""
    cache = load_cache(root)

    path_str = str(path)

    # Update recent files (max 20)
    if path_str in cache.recent_files:
        cache.recent_files.remove(path_str)
    cache.recent_files.insert(0, path_str)
    cache.recent_files = cache.recent_files[:20]

    # Update hot files
    cache.hot_files[path_str] = cache.hot_files.get(path_str, 0) + 1

    save_cache(cache, root)


def get_recent_context(
    limit: int = 5,
    max_lines: int = 50,
    root: Path = None
) -> ContextResult:
    """Get context from recently accessed files."""
    cache = load_cache(root)
    root = root or find_project_root() or Path.cwd()

    files = []
    token_count = 0

    for file_path in cache.recent_files[:limit]:
        path = Path(file_path)
        if not path.is_absolute():
            path = root / path

        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[:max_lines]
                    content = ''.join(lines)
                    files.append((str(path), content))
                    token_count += len(content.split())
            except Exception:
                pass

    return ContextResult(files=files, token_count=token_count, source='recent')


def get_hot_context(
    limit: int = 5,
    max_lines: int = 50,
    root: Path = None
) -> ContextResult:
    """Get context from most frequently accessed files."""
    cache = load_cache(root)
    root = root or find_project_root() or Path.cwd()

    # Sort by access count
    sorted_files = sorted(cache.hot_files.items(), key=lambda x: x[1], reverse=True)

    files = []
    token_count = 0

    for file_path, _ in sorted_files[:limit]:
        path = Path(file_path)
        if not path.is_absolute():
            path = root / path

        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[:max_lines]
                    content = ''.join(lines)
                    files.append((str(path), content))
                    token_count += len(content.split())
            except Exception:
                pass

    return ContextResult(files=files, token_count=token_count, source='hot')


def get_semantic_context(
    query: str,
    limit: int = 5,
    root: Path = None
) -> ContextResult:
    """Get context via semantic search."""
    root = root or find_project_root() or Path.cwd()

    files = []
    token_count = 0

    try:
        from .vector_store import VectorStore
        store = VectorStore(root / '.mcp' / 'vector_index')

        if store.load():
            results = store.search(query, k=limit)

            for result in results:
                files.append((result.chunk.path, result.chunk.content))
                token_count += len(result.chunk.content.split())
    except Exception:
        pass

    # Update cache with query
    cache = load_cache(root)
    cache.last_query = query
    save_cache(cache, root)

    return ContextResult(files=files, token_count=token_count, source='semantic')


def get_dependency_context(
    file_path: Path,
    root: Path = None
) -> ContextResult:
    """Get context from file dependencies (imports)."""
    root = root or find_project_root() or Path.cwd()

    files = []
    token_count = 0

    try:
        from .treesitter_utils import parse_file
        parsed = parse_file(file_path)

        for imp in parsed.imports:
            # Try to resolve import to file
            parts = imp.replace('from ', '').replace('import ', '').split()[0].split('.')

            for i in range(len(parts), 0, -1):
                possible_path = root / '/'.join(parts[:i]) + '.py'
                if possible_path.exists():
                    try:
                        with open(possible_path, 'r', encoding='utf-8') as f:
                            content = f.read()[:2000]
                            files.append((str(possible_path), content))
                            token_count += len(content.split())
                    except Exception:
                        pass
                    break
    except Exception:
        pass

    return ContextResult(files=files, token_count=token_count, source='dependency')


def generate_dynamic_project_map(root: Path, max_depth: int = 3) -> str:
    """Generate a highly compressed dynamic project directory layout."""
    lines = ["# Dynamic Project Map"]
    exclude_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.mcp', 'build', 'dist', '.pytest_cache'}
    
    def walk(directory: Path, current_depth: int, indent: str):
        if current_depth > max_depth:
            return
        
        try:
            items = sorted(list(directory.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
        except Exception:
            return
            
        for item in items:
            if item.name in exclude_dirs or item.name.startswith('.'):
                continue
            
            if item.is_dir():
                try:
                    py_files = sum(1 for p in item.rglob('*.py') if not any(x in p.parts for x in exclude_dirs))
                except Exception:
                    py_files = 0
                
                suffix = f" ({py_files} python files)" if py_files > 0 else ""
                lines.append(f"{indent}[DIR] {item.name}/{suffix}")
                walk(item, current_depth + 1, indent + "  ")
            else:
                if item.suffix in ('.py', '.js', '.ts', '.go', '.rs', '.json', '.md', '.html', '.css'):
                    try:
                        sz = item.stat().st_size
                        lines.append(f"{indent}[FILE] {item.name} ({sz} bytes)")
                    except Exception:
                        lines.append(f"{indent}[FILE] {item.name}")
                        
    walk(root, 1, "  ")
    return "\n".join(lines)


def compress_code_block(content: str, max_lines: int = 25, query: str = "") -> str:
    """
    Compresses a python code block to retain structure, class/method signatures,
    docstrings, and relevant keyword matches while omitting verbose bodies.
    """
    lines = content.split('\n')
    if len(lines) <= max_lines:
        return content

    try:
        tree = ast.parse(content)
    except Exception:
        # Fallback to simple line-based truncation if non-parsable or non-Python
        keep = []
        query_terms = [q.lower() for q in query.split() if len(q) > 2]
        for i, line in enumerate(lines):
            stripped = line.strip()
            is_header = stripped.startswith(('def ', 'class ', 'import ', 'from ')) or stripped.endswith(':')
            has_query = any(q in line.lower() for q in query_terms) if query_terms else False
            
            if i < 5 or i >= len(lines) - 2 or is_header or has_query:
                keep.append((i, line))
                
        formatted = []
        last_idx = -1
        for idx, line in keep:
            if last_idx != -1 and idx > last_idx + 1:
                indent = " " * (len(line) - len(line.lstrip()))
                formatted.append(f"{indent}... [{idx - last_idx - 1} lines compressed] ...")
            formatted.append(line)
            last_idx = idx
        return "\n".join(formatted)

    omitted_ranges = []
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if not body:
                continue
                
            start_idx = body[0].lineno - 1
            doc = ast.get_docstring(node)
            if doc and len(body) > 1:
                start_idx = body[1].lineno - 1
                
            end_idx = node.end_lineno - 1 if hasattr(node, 'end_lineno') else len(lines)
            
            body_text = "\n".join(lines[start_idx:end_idx+1])
            query_terms = [q.lower() for q in query.split() if len(q) > 2]
            has_query = any(q in body_text.lower() for q in query_terms) if query_terms else False
            
            if end_idx - start_idx > 3 and not has_query:
                omitted_ranges.append((start_idx, end_idx))

    if not omitted_ranges:
        return "\n".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} lines truncated] ..."

    omitted_ranges.sort()
    merged_ranges = []
    for r in omitted_ranges:
        if not merged_ranges:
            merged_ranges.append(r)
        else:
            prev_s, prev_e = merged_ranges[-1]
            curr_s, curr_e = r
            if curr_s <= prev_e + 1:
                merged_ranges[-1] = (prev_s, max(prev_e, curr_e))
            else:
                merged_ranges.append(r)

    compressed_lines = []
    last_idx = 0
    for start, end in merged_ranges:
        compressed_lines.extend(lines[last_idx:start])
        next_line = lines[start] if start < len(lines) else ""
        indent = " " * (len(next_line) - len(next_line.lstrip()))
        compressed_lines.append(f"{indent}... [{end - start + 1} lines body compressed] ...")
        last_idx = end + 1
        
    compressed_lines.extend(lines[last_idx:])
    return "\n".join(compressed_lines)


def get_project_map(root: Path, budget: int) -> str:
    """Layer 1: Get high-level project map."""
    summary_path = root / "CODEBASE_SUMMARY.md"
    if summary_path.exists():
        try:
            content = summary_path.read_text(encoding='utf-8')
            if "## Directory Structure" in content:
                structure = content.split("## Directory Structure")[1].split("##")[0]
                return f"# Project Map\n{structure[:budget]}"
            return content[:budget]
        except Exception:
            pass
    return generate_dynamic_project_map(root)[:budget]

def get_auto_context(
    task: str = "",
    token_budget: int = 8000, # Increased default for deep context
    root: Path = None
) -> str:
    """Get hierarchically layered context for AI agent using sliding-scale budget partitions."""
    root = root or find_project_root() or Path.cwd()

    # 1. Initialize budget engine and partitions
    engine = ContextBudgetEngine(token_budget)
    limits = engine.get_limits()
    budget_map = limits.get("map", int(token_budget * 0.05))
    budget_activity = limits.get("activity", int(token_budget * 0.15))
    budget_active = limits.get("active", int(token_budget * 0.45))
    budget_semantic = limits.get("semantic", int(token_budget * 0.35))

    layers = []

    # Layer 1: Project Map
    project_map = get_project_map(root, budget_map)
    if project_map:
        layers.append(project_map)

    # Preemptive Background Health Alerts
    health_alerts = []
    health_path = root / '.mcp' / 'active_health.json'
    if health_path.exists():
        try:
            with open(health_path, 'r', encoding='utf-8') as f:
                health = json.load(f)
                
            status = health.get("status", "Unknown")
            last_checked = health.get("last_checked", "")
            syntax_errors = health.get("syntax_errors", [])
            test_results = health.get("test_results", {})
            ripple_warnings = health.get("ripple_warnings", [])
            
            health_alerts.append(f"Preemptive Automation Daemon Status: {status} (Last Checked: {last_checked})")
            
            if syntax_errors:
                health_alerts.append("WARNING: Real-Time Syntax Errors Detected:")
                for err in syntax_errors:
                    health_alerts.append(f"  - File: {err.get('file')} (Line {err.get('line')}): {err.get('error')} -> '{err.get('text')}'")
                    
            if test_results:
                t_status = test_results.get("status", "Healthy")
                passed = test_results.get("passed", 0)
                failed = test_results.get("failed", 0)
                failures = test_results.get("failures", [])
                
                if failed > 0:
                    health_alerts.append(f"CRITICAL: Active Test Suite Failure ({t_status}):")
                    health_alerts.append(f"  - Passed Suites: {passed}, Failed Suites: {failed}")
                    health_alerts.append(f"  - Failed Suites List: {', '.join(failures)}")
                    logs = test_results.get("logs", "")
                    if logs:
                        log_lines = logs.split('\n')
                        health_alerts.append("  - Recent Test Failure Output:")
                        for l in log_lines[-15:]:
                            health_alerts.append(f"    {l}")
                else:
                    health_alerts.append(f"Test Suite Status: {t_status} (Passed: {passed})")
                    
            if ripple_warnings:
                health_alerts.append("Downstream Ripple Impact Warnings:")
                for rip in ripple_warnings:
                    m_file = rip.get("modified_file")
                    count = rip.get("impacted_count")
                    i_files = rip.get("impacted_files", [])
                    health_alerts.append(f"  - Modification of '{m_file}' impacts {count} downstream files:")
                    for i_f in i_files:
                        health_alerts.append(f"    * {i_f}")
        except Exception:
            pass

    if health_alerts:
        layers.append("# Active System Health & Compiler Warnings\n" + "\n".join(health_alerts))

    # Layer 2: Memory & Action Ledger
    memories = []
    try:
        from .memory import get_store
        store = get_store()
        recent_mems = store.recall(task) if task else store.list_all()
        recent_mems.sort(key=lambda m: m.updated or m.created, reverse=True)

        mem_tokens_used = 0
        for mem in recent_mems[:5]:
            encoded = f"[{mem.key}] {mem.value}"
            if mem_tokens_used + len(encoded.split()) < budget_activity // 2:
                memories.append(encoded)
                mem_tokens_used += len(encoded.split())
                
        # Also query the Vectorized Action Ledger if available
        try:
            actions = store.search_activity_stream(task if task else "setup", limit=5)
            if actions:
                memories.append("\nRecent Vectorized Action Timeline:")
                for act in actions:
                    act_encoded = f"  - [{act.get('timestamp')}] {act.get('tool_name')}({act.get('arguments')[:50]}) -> {act.get('result_status')}: {act.get('summary')}"
                    if mem_tokens_used + len(act_encoded.split()) < budget_activity:
                        memories.append(act_encoded)
                        mem_tokens_used += len(act_encoded.split())
        except Exception:
            pass
    except Exception:
        pass

    if memories:
        layers.append("# Recent Memory & Decisions\n" + "\n".join(memories))

    # Layer 3: Active & Dependencies
    files_to_budget = []  # List of (path_str, raw_content, priority)
    
    # 3a. Recent Files (Active)
    recent = get_recent_context(limit=3, root=root)
    active_paths = [path for path, _ in recent.files]
    
    # 3b. Read dependency graph if available
    graph = MacroCodebaseGraph(root)
    graph_loaded = graph.load()
    
    dep_paths = []
    if graph_loaded:
        for path in active_paths:
            rel_path = str(Path(path).relative_to(root)).replace('\\', '/')
            if rel_path in graph.dependencies:
                for dep in graph.dependencies[rel_path]:
                    dep_abs = root / dep
                    if dep_abs.exists() and str(dep_abs) not in active_paths:
                        dep_paths.append(str(dep_abs))
    else:
        # Fallback to older import parser
        for path, _ in recent.files:
            try:
                from .deps import analyze_imports
                deps = analyze_imports(Path(path))
                if deps:
                    for imp in list(deps.imports)[:2]:
                        local_path = root / f"{imp.replace('.', '/')}.py"
                        if local_path.exists() and str(local_path) not in active_paths:
                            dep_paths.append(str(local_path))
            except Exception:
                pass

    # Read and add files with appropriate priorities
    # Top active file: priority 0 (Keep full)
    # Next 2 active files: priority 1 (AST Skeleton)
    # Dependency files: priority 1 (AST Skeleton)
    for i, (path, content) in enumerate(recent.files):
        priority = 0 if i == 0 else 1
        files_to_budget.append((path, content, priority))
        
    for path in dep_paths[:3]: # Limit dependency files to keep performance fast
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            files_to_budget.append((path, content, 1))
        except Exception:
            pass

    # Budget primary files using dynamic scaling
    budgeted_active_files = engine.format_and_budget_files(files_to_budget, budget_active)

    # Layer 4: Semantic Search
    files_to_budget_semantic = []
    if task:
        semantic = get_semantic_context(task, limit=5, root=root)
        already_included = {f[0] for f in budgeted_active_files}
        for path, content in semantic.files:
            if path not in already_included:
                files_to_budget_semantic.append((path, content, 2)) # Priority 2: Low (summary/header)

    budgeted_semantic_files = engine.format_and_budget_files(files_to_budget_semantic, budget_semantic)

    # Assemble Context Payload
    final_output = ["# Deep Context Auto-Loader", ""]
    final_output.extend(layers)

    if budgeted_active_files:
        final_output.append("# Active Context")
        for path, formatted, _ in budgeted_active_files:
            final_output.append(f"## {Path(path).name}\n# {path}\n```python\n{formatted}\n```\n")

    if budgeted_semantic_files:
        final_output.append("# Semantic Context")
        for path, formatted, _ in budgeted_semantic_files:
            final_output.append(f"## {Path(path).name} (Relevant)\n# {path}\n```python\n{formatted}\n```\n")

    return "\n".join(final_output)

# ... (Main function kept same, calling get_auto_context)


def update_task(task: str, root: Path = None):
    """Update current task in cache."""
    cache = load_cache(root)
    cache.last_task = task
    save_cache(cache, root)


def main():
    """CLI entry point."""
    Console.header("Auto-Context Loader")

    args = [a for a in sys.argv[1:] if not a.startswith('-')]

    root = find_project_root() or Path.cwd()

    if '--recent' in sys.argv:
        result = get_recent_context(root=root)
        Console.info(f"Recent files: {len(result.files)}")
        for path, _ in result.files:
            print(f"  - {path}")
        return 0

    if '--hot' in sys.argv:
        result = get_hot_context(root=root)
        Console.info(f"Hot files: {len(result.files)}")
        for path, _ in result.files:
            print(f"  - {path}")
        return 0

    if '--auto' in sys.argv or not args:
        task = ' '.join(args) if args else ""
        context = get_auto_context(task=task, root=root)
        print(context)
        return 0

    # Semantic search with query
    query = ' '.join(args)
    result = get_semantic_context(query, root=root)

    Console.info(f"Found {len(result.files)} relevant files for: {query}")
    for path, content in result.files:
        print(f"\n## {path}")
        print(content[:500])

    return 0


if __name__ == "__main__":
    sys.exit(main())

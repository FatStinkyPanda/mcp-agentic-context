"""
Unified Index Manager
=====================
Run all indexes at once for complete codebase intelligence.

Usage:
    python mcp.py index-all      # Full reindex
    python mcp.py index-all --what  # Show what's indexed
"""

from datetime import datetime
from pathlib import Path
import json
import sys
import time

from .utils import Console, find_project_root


def get_changed_files(root: Path, last_index_time: float) -> list:
    """Find all files in the project modified after last_index_time."""
    changed = []
    exclude = {'.git', 'node_modules', 'venv', '.venv', '__pycache__', 'vendor', '.mcp', 'build', 'dist'}

    # We want to scan common source file extensions
    valid_exts = {'.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java', '.c', '.cpp', '.h', '.hpp', '.md', '.json', '.yaml', '.yml'}

    for path in root.rglob('*'):
        # Check if any parent of the path is in the exclude set
        try:
            parts = path.relative_to(root).parts
            if any(part in exclude for part in parts):
                continue
            if path.is_file() and path.suffix in valid_exts:
                mtime = path.stat().st_mtime
                if mtime > last_index_time:
                    changed.append(path)
        except Exception:
            pass

    return changed


def run_all_indexes(root: Path = None, verbose: bool = True, force_full: bool = False) -> dict:
    """Run all indexes (incrementally by default) and return summary."""
    root = root or find_project_root() or Path.cwd()
    summary_path = root / '.mcp' / 'index_summary.json'

    last_index_time = 0.0
    is_incremental = False
    changed_files = None

    if not force_full and summary_path.exists():
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary_data = json.load(f)
            ts_str = summary_data.get('timestamp')
            if ts_str:
                if ts_str.endswith('Z'):
                    ts_str = ts_str.replace('Z', '+00:00')
                else:
                    ts_str += '+00:00'
                dt = datetime.fromisoformat(ts_str)
                last_index_time = dt.timestamp()
                is_incremental = True
        except Exception:
            pass

    if is_incremental:
        changed_files = get_changed_files(root, last_index_time)
        if verbose:
            if not changed_files:
                Console.ok("Index is already up to date. No files modified since last index.")
                try:
                    with open(summary_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    pass
            else:
                Console.info(f"Incremental Index Build: detected {len(changed_files)} modified files.")
    elif verbose:
        Console.header("Full Index Build")
        Console.info(f"Indexing {root}...")

    start_time = time.time()
    results = {}

    # 1. Semantic code index
    if verbose:
        Console.info("1/7 Semantic code index...")
    try:
        from .vector_store import VectorStore
        store = VectorStore(root / '.mcp' / 'vector_index')
        count = store.index_codebase(root, changed_files=changed_files)
        results['semantic'] = {'status': 'ok', 'items': count}
    except Exception as e:
        results['semantic'] = {'status': 'error', 'error': str(e)}

    # 2. Git history index
    if verbose:
        Console.info("2/7 Git history index...")
    try:
        from .git_index import index_git_history
        index = index_git_history(root, since="3 months")
        results['git'] = {'status': 'ok', 'commits': index.get('commit_count', 0)}
    except Exception as e:
        results['git'] = {'status': 'error', 'error': str(e)}

    # 3. TODO/FIXME index
    if verbose:
        Console.info("3/7 TODO/FIXME index...")
    try:
        from .todo_index import index_todos
        index = index_todos(root, changed_files=changed_files)
        results['todos'] = {'status': 'ok', 'items': index.get('total', 0)}
    except Exception as e:
        results['todos'] = {'status': 'error', 'error': str(e)}

    # 4. Impact graph
    if verbose:
        Console.info("4/7 Dependency impact graph...")
    try:
        from .impact import save_impact_graph
        save_impact_graph(root)
        results['impact'] = {'status': 'ok'}
    except Exception as e:
        results['impact'] = {'status': 'error', 'error': str(e)}

    # 5. Documentation index
    if verbose:
        Console.info("5/7 Documentation index...")
    try:
        from .doc_index import index_documentation
        index = index_documentation(root)
        results['docs'] = {'status': 'ok', 'items': index.get('total_items', 0)}
    except Exception as e:
        results['docs'] = {'status': 'error', 'error': str(e)}

    # 6. Config index
    if verbose:
        Console.info("6/7 Config index...")
    try:
        from .config_index import index_configs
        index = index_configs(root)
        results['config'] = {'status': 'ok', 'vars': len(index.get('env_vars', {}))}
    except Exception as e:
        results['config'] = {'status': 'error', 'error': str(e)}

    # 7. Coverage (if available)
    if verbose:
        Console.info("7/7 Coverage index...")
    try:
        from .coverage_index import index_coverage
        index = index_coverage(root)
        results['coverage'] = {'status': 'ok', 'files': index.get('total_files', 0)}
    except Exception as e:
        results['coverage'] = {'status': 'skipped', 'reason': 'No coverage data'}

    elapsed = time.time() - start_time

    # Save summary
    summary = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'duration_seconds': round(elapsed, 2),
        'root': str(root),
        'indexes': results
    }

    summary_path = root / '.mcp' / 'index_summary.json'
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)

    if verbose:
        print("")
        Console.ok(f"Complete in {elapsed:.1f}s")
        show_index_status(root)

    return summary


def show_index_status(root: Path = None):
    """Show what's currently indexed."""
    root = root or find_project_root() or Path.cwd()
    mcp_dir = root / '.mcp'

    print("\n## Index Status")
    print("")

    indexes = [
        ('vector_index', 'Semantic Code', 'chunks.json'),
        ('git_index.json', 'Git History', None),
        ('todo_index.json', 'TODOs/FIXMEs', None),
        ('impact_graph.json', 'Impact Graph', None),
        ('doc_index.json', 'Documentation', None),
        ('config_index.json', 'Config', None),
        ('coverage_index.json', 'Coverage', None),
    ]

    for idx_name, display_name, sub_file in indexes:
        idx_path = mcp_dir / idx_name

        if sub_file:
            idx_path = idx_path / sub_file

        if idx_path.exists():
            size = idx_path.stat().st_size
            size_str = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
            print(f"  * {display_name:20} ({size_str})")
        else:
            print(f"  - {display_name:20} (not indexed)")


def main():
    """CLI entry point."""
    root = find_project_root() or Path.cwd()

    if '--what' in sys.argv or '--status' in sys.argv:
        Console.header("Index Status")
        show_index_status(root)
        return 0

    if '--quick' in sys.argv:
        # Quick mode: only semantic + todos
        Console.header("Quick Index")

        try:
            from .vector_store import VectorStore
            store = VectorStore(root / '.mcp' / 'vector_index')
            store.index_codebase(root)
        except Exception:
            pass

        try:
            from .todo_index import index_todos
            index_todos(root)
        except Exception:
            pass

        Console.ok("Quick index complete")
        return 0

    # Full index
    force_full = '--full' in sys.argv
    run_all_indexes(root, verbose=True, force_full=force_full)

    return 0


if __name__ == "__main__":
    sys.exit(main())

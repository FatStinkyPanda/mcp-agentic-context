"""
Auto-Learning Integration
=========================
Automatic recording of tool outcomes for continuous improvement.

Usage:
    Import and wrap tool functions for auto-learning.
"""

from pathlib import Path
from typing import Any, Callable, Optional
import functools
import sys
import traceback

# Import learning system
try:
    from .learning import get_store, record_feedback, record_error as _record_error
except ImportError:
    # Fallback if not running as module
    def record_feedback(*args, **kwargs): pass
    def _record_error(*args, **kwargs): pass


def auto_learn(tool_name: str):
    """Decorator to auto-record tool outcomes."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                result = func(*args, **kwargs)

                # Record success
                context = f"args={args[:2]}" if args else ""
                record_feedback(tool_name, 'success', context)

                return result
            except Exception as e:
                # Record failure
                tb = traceback.format_exc()
                record_error(
                    error_type=type(e).__name__,
                    pattern=str(e)[:100],
                    fix="",
                    context=f"Tool: {tool_name}"
                )
                record_feedback(tool_name, 'failure', str(e)[:100])
                raise

        return wrapper
    return decorator


def record_error(
    error_type: str,
    pattern: str,
    fix: str = "",
    context: str = ""
):
    """Record an error for learning."""
    try:
        from .learning import get_store
        store = get_store()
        store.record_error(error_type, pattern, fix, context)
    except Exception:
        pass  # Silent fail for learning


def record_correction(before: str, after: str, context: str = ""):
    """Record a user correction for learning."""
    try:
        from .learning import get_store
        store = get_store()
        store.record_feedback(
            action='correction',
            outcome='applied',
            context=f"Before: {before[:50]}... After: {after[:50]}...",
            details={'before': before, 'after': after}
        )
    except Exception:
        pass


def suggest_from_history(error_type: str, pattern: str) -> Optional[str]:
    """Get fix suggestion from learning history."""
    try:
        from .learning import get_store
        store = get_store()
        return store.suggest_fix(error_type, pattern)
    except Exception:
        return None


def get_success_rate(tool_name: str) -> float:
    """Get success rate for a tool."""
    try:
        from .learning import get_store
        store = get_store()
        return store.get_action_success_rate(tool_name)
    except Exception:
        return 0.5  # Unknown


# =============================================================================
# ENHANCED LEARNING: Commit, Test, and Behavioral Patterns
# =============================================================================

import json
import re
from datetime import datetime, timedelta
from collections import defaultdict

from .utils import find_project_root, get_project_boundary, run_git_command, Console


def _get_learning_path(root: Path) -> Path:
    """Get path to enhanced learning data."""
    return root / '.mcp' / 'enhanced_learning.json'


def _load_enhanced_data(root: Path = None) -> dict:
    """Load enhanced learning data."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    path = _get_learning_path(root)
    
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    
    return {
        'effectiveness_scores': {},
        'access_sequences': {},
        'auto_lessons': [],
        'success_patterns': [],
        'failure_patterns': [],
        'commits_learned': 0,
        'tests_learned': 0,
    }


def _save_enhanced_data(data: dict, root: Path = None):
    """Save enhanced learning data."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    path = _get_learning_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


# Lesson extraction patterns
LESSON_PATTERNS = [
    (r'fix[:\s]+use\s+(\w+)\s+instead\s+of\s+(\w+)', 'Use {0} instead of {1}'),
    (r"fix[:\s]+(?:don'?t|do\s+not)\s+(.+)", 'Do not {0}'),
    (r'fix[:\s]+always\s+(.+)', 'Always {0}'),
    (r'fix[:\s]+never\s+(.+)', 'Never {0}'),
    (r'revert[:\s]+"?(.+)"?', 'Reverted: {0}'),
]


def learn_from_commit(root: Path = None) -> int:
    """Learn lessons from the most recent commit."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = _load_enhanced_data(root)
    
    message = run_git_command(['log', '-1', '--format=%s'], cwd=root)
    if not message:
        return 0
    
    files_output = run_git_command(['diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'], cwd=root)
    changed_files = [f for f in (files_output or '').strip().split('\n') if f.endswith('.py')]
    
    lessons_learned = 0
    
    # Extract lessons from commit message
    for pattern, template in LESSON_PATTERNS:
        match = re.search(pattern, message.lower())
        if match:
            lesson = template.format(*match.groups())
            lesson = lesson[0].upper() + lesson[1:]
            if lesson not in data['auto_lessons']:
                data['auto_lessons'].append(lesson)
                lessons_learned += 1
                Console.ok(f"Learned: {lesson}")
    
    # Boost effectiveness for committed files
    if changed_files:
        data['success_patterns'].append({
            'files': changed_files,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
        for f in changed_files:
            current = data['effectiveness_scores'].get(f, 0.5)
            data['effectiveness_scores'][f] = min(1.0, current + 0.05)
    
    data['commits_learned'] = data.get('commits_learned', 0) + 1
    data['success_patterns'] = data['success_patterns'][-100:]
    
    _save_enhanced_data(data, root)
    
    # Append lessons to lessons_learned.md
    if lessons_learned > 0:
        _append_lessons(data['auto_lessons'][-lessons_learned:], root)
    
    return lessons_learned


def _append_lessons(lessons: list, root: Path):
    """Append lessons to lessons_learned.md."""
    lessons_path = root / '.mcp' / 'lessons_learned.md'
    lessons_path.parent.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d")
    
    content = lessons_path.read_text(encoding='utf-8') if lessons_path.exists() else "# Lessons Learned\n\n"
    
    for lesson in lessons:
        if lesson not in content:
            content += f"- {lesson} (auto: {timestamp})\n"
    
    lessons_path.write_text(content, encoding='utf-8')


def learn_from_test(exit_code: int, root: Path = None):
    """Learn from test result (0=pass, non-zero=fail)."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = _load_enhanced_data(root)
    
    files_output = run_git_command(['diff', '--name-only'], cwd=root) or ''
    staged_output = run_git_command(['diff', '--cached', '--name-only'], cwd=root) or ''
    changed_files = list(set(f for f in (files_output + staged_output).split('\n') if f.endswith('.py')))
    
    if exit_code == 0:
        Console.ok("Test passed - boosting effectiveness")
        for f in changed_files:
            current = data['effectiveness_scores'].get(f, 0.5)
            data['effectiveness_scores'][f] = min(1.0, current + 0.1)
    else:
        Console.warn("Test failed - recording failure pattern")
        data['failure_patterns'].append({'files': changed_files, 'timestamp': datetime.utcnow().isoformat() + 'Z'})
        for f in changed_files:
            current = data['effectiveness_scores'].get(f, 0.5)
            data['effectiveness_scores'][f] = max(0.1, current - 0.1)
    
    data['tests_learned'] = data.get('tests_learned', 0) + 1
    data['failure_patterns'] = data['failure_patterns'][-50:]
    
    _save_enhanced_data(data, root)


def record_file_access(file_path: str, root: Path = None):
    """Record file access for behavioral pattern learning."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = _load_enhanced_data(root)
    
    recent_key = '_last_accessed'
    last = data.get(recent_key, '')
    
    if last and last != file_path:
        if last not in data['access_sequences']:
            data['access_sequences'][last] = {}
        current = data['access_sequences'][last].get(file_path, 0.0)
        data['access_sequences'][last][file_path] = min(1.0, current + 0.1)
    
    data[recent_key] = file_path
    _save_enhanced_data(data, root)


def predict_next_files(current_file: str, root: Path = None, limit: int = 5) -> list:
    """Predict next likely files based on access patterns."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = _load_enhanced_data(root)
    
    sequences = data.get('access_sequences', {}).get(current_file, {})
    predictions = sorted(sequences.items(), key=lambda x: x[1], reverse=True)
    return predictions[:limit]


def get_effectiveness_score(file_path: str, root: Path = None) -> float:
    """Get effectiveness score for a file."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = _load_enhanced_data(root)
    return data.get('effectiveness_scores', {}).get(file_path, 0.5)


def consolidate_session(root: Path = None):
    """End-of-session consolidation - decay old scores, prune data."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = _load_enhanced_data(root)
    
    Console.info("Consolidating learning session...")
    
    # Decay effectiveness toward neutral
    for f in list(data.get('effectiveness_scores', {}).keys()):
        current = data['effectiveness_scores'][f]
        if current > 0.5:
            data['effectiveness_scores'][f] = max(0.5, current - 0.02)
        elif current < 0.5:
            data['effectiveness_scores'][f] = min(0.5, current + 0.02)
    
    # Prune old patterns
    cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat() + 'Z'
    data['success_patterns'] = [p for p in data.get('success_patterns', []) if p.get('timestamp', '') > cutoff]
    data['failure_patterns'] = [p for p in data.get('failure_patterns', []) if p.get('timestamp', '') > cutoff]
    
    _save_enhanced_data(data, root)
    Console.ok("Session consolidated")


def main():
    """CLI entry point."""
    from .utils import Console
    Console.header("Auto-Learning System")
    
    root = get_project_boundary() or find_project_root() or Path.cwd()
    
    # Enhanced CLI options
    if '--from-commit' in sys.argv:
        count = learn_from_commit(root)
        Console.ok(f"Learned {count} lessons from commit")
        return 0
    
    if '--pre-commit' in sys.argv:
        # Record staged files for pattern learning
        Console.info("Recording pre-commit patterns...")
        files_output = run_git_command(['diff', '--cached', '--name-only'], cwd=root) or ''
        for f in files_output.strip().split('\n'):
            if f.endswith('.py'):
                record_file_access(str(root / f), root)
        Console.ok("Pre-commit patterns recorded")
        return 0
    
    for i, arg in enumerate(sys.argv):
        if arg == '--from-test' and i + 1 < len(sys.argv):
            learn_from_test(int(sys.argv[i + 1]), root)
            return 0
    
    if '--consolidate' in sys.argv:
        consolidate_session(root)
        return 0
    
    # Show combined stats
    try:
        from .learning import get_store
        store = get_store()
        analysis = store.analyze_patterns()
        
        print(f"\n## Tool Success Rates")
        for action, d in analysis.get('action_outcomes', {}).items():
            rate = d['success_rate'] * 100
            status = "+" if rate > 80 else "!" if rate > 50 else "-"
            print(f"  {status} {action}: {rate:.0f}%")
    except Exception:
        pass
    
    # Show enhanced learning stats
    data = _load_enhanced_data(root)
    print(f"\n## Enhanced Learning")
    print(f"  Commits learned: {data.get('commits_learned', 0)}")
    print(f"  Tests learned: {data.get('tests_learned', 0)}")
    print(f"  Auto-lessons: {len(data.get('auto_lessons', []))}")
    print(f"  Files with scores: {len(data.get('effectiveness_scores', {}))}")
    
    if data.get('auto_lessons'):
        print(f"\n## Recent Auto-Lessons")
        for lesson in data['auto_lessons'][-5:]:
            print(f"  - {lesson}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

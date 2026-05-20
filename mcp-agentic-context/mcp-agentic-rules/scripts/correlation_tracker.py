"""
Correlation Tracker
===================
Automated system for tracking and learning code correlations.

Monitors:
- File access patterns (which files are accessed together)
- Git modifications (which files change together)
- Test correlations (which files fail together)
- Error patterns (which issues co-occur)

Usage:
    python mcp.py learn-patterns           # Analyze git history
    python mcp.py correlate                # Show file correlations
    python mcp.py correlate "file.py"      # Show correlations for file
"""

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple

from .utils import (
    find_project_root,
    get_project_boundary,
    run_git_command,
    Console
)


@dataclass
class CorrelationData:
    """Stores all correlation learning data."""
    root: Path
    
    # Co-modification: which files change together
    comod_counts: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    
    # Access patterns: which files are accessed together
    access_counts: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    
    # Test correlations: which files fail together
    test_correlations: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    
    # Patterns learned
    learned_patterns: List[str] = field(default_factory=list)
    
    # Metadata
    last_updated: str = ""
    commits_analyzed: int = 0
    
    def to_dict(self) -> dict:
        return {
            'root': str(self.root),
            'comod_counts': {k: dict(v) for k, v in self.comod_counts.items()},
            'access_counts': {k: dict(v) for k, v in self.access_counts.items()},
            'test_correlations': {k: dict(v) for k, v in self.test_correlations.items()},
            'learned_patterns': self.learned_patterns,
            'last_updated': self.last_updated,
            'commits_analyzed': self.commits_analyzed,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CorrelationData':
        cd = cls(root=Path(data['root']))
        
        for k, v in data.get('comod_counts', {}).items():
            cd.comod_counts[k] = defaultdict(int, v)
        
        for k, v in data.get('access_counts', {}).items():
            cd.access_counts[k] = defaultdict(int, v)
        
        for k, v in data.get('test_correlations', {}).items():
            cd.test_correlations[k] = defaultdict(int, v)
        
        cd.learned_patterns = data.get('learned_patterns', [])
        cd.last_updated = data.get('last_updated', '')
        cd.commits_analyzed = data.get('commits_analyzed', 0)
        
        return cd


def get_correlation_path(root: Path) -> Path:
    """Get path to correlation data file."""
    return root / '.mcp' / 'correlations.json'


def load_correlations(root: Path = None) -> CorrelationData:
    """Load correlation data from disk."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    corr_path = get_correlation_path(root)
    
    if corr_path.exists():
        try:
            with open(corr_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return CorrelationData.from_dict(data)
        except Exception:
            pass
    
    return CorrelationData(root=root)


def save_correlations(data: CorrelationData):
    """Save correlation data to disk."""
    corr_path = get_correlation_path(data.root)
    corr_path.parent.mkdir(parents=True, exist_ok=True)
    
    data.last_updated = datetime.utcnow().isoformat() + 'Z'
    
    with open(corr_path, 'w', encoding='utf-8') as f:
        json.dump(data.to_dict(), f, indent=2)


def analyze_git_history(root: Path, max_commits: int = 200) -> CorrelationData:
    """
    Analyze git history to learn file correlations.
    
    This is the main learning function - extracts patterns from history.
    """
    Console.info(f"Analyzing git history (last {max_commits} commits)...")
    
    data = load_correlations(root)
    
    # Get commit log with files
    output = run_git_command(
        ['log', '--name-only', '--format=%H|%an|%s', f'-n{max_commits}'],
        cwd=root
    )
    
    if not output:
        Console.warn("Could not get git history")
        return data
    
    # Parse commits
    commits = output.strip().split('\n\n')
    new_commits = 0
    
    for commit_block in commits:
        lines = commit_block.strip().split('\n')
        if not lines:
            continue
        
        # Parse header
        header = lines[0]
        files = [f for f in lines[1:] if f.strip()]
        
        if len(files) < 2:
            continue  # Need at least 2 files to correlate
        
        # Record co-modifications
        py_files = [f for f in files if f.endswith('.py')]
        
        for i, f1 in enumerate(py_files):
            for f2 in py_files[i+1:]:
                data.comod_counts[f1][f2] += 1
                data.comod_counts[f2][f1] += 1
        
        new_commits += 1
    
    data.commits_analyzed += new_commits
    Console.ok(f"Analyzed {new_commits} commits with multi-file changes")
    
    # Extract patterns
    data.learned_patterns = extract_patterns(data)
    
    save_correlations(data)
    
    return data


def extract_patterns(data: CorrelationData) -> List[str]:
    """Extract high-confidence patterns from correlation data."""
    patterns = []
    
    # Find highly correlated file pairs
    for f1, others in data.comod_counts.items():
        for f2, count in others.items():
            if count >= 5:  # Must co-occur at least 5 times
                p1 = Path(f1).name
                p2 = Path(f2).name
                pattern = f"{p1} and {p2} are strongly correlated ({count} co-modifications)"
                if pattern not in patterns:
                    patterns.append(pattern)
    
    # Limit to top 20 patterns
    return patterns[:20]


def get_correlations_for_file(file_path: str, data: CorrelationData, limit: int = 10) -> List[Tuple[str, int, str]]:
    """
    Get files correlated with the given file.
    
    Returns: List of (related_file, strength, reason)
    """
    results = []
    file_name = Path(file_path).name
    
    # Try to match by name or full path
    for key in data.comod_counts.keys():
        if file_name in key or file_path in key:
            for related, count in data.comod_counts[key].items():
                if count > 0:
                    results.append((related, count, 'co-modified'))
    
    # Also check access correlations
    for key in data.access_counts.keys():
        if file_name in key or file_path in key:
            for related, count in data.access_counts[key].items():
                if count > 0:
                    # Check if already in results
                    existing = next((r for r in results if r[0] == related), None)
                    if existing:
                        # Boost existing
                        idx = results.index(existing)
                        results[idx] = (related, existing[1] + count, 'co-modified+accessed')
                    else:
                        results.append((related, count, 'co-accessed'))
    
    # Sort by strength
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:limit]


def record_file_access(file_path: str, root: Path = None):
    """
    Record that a file was accessed.
    
    Called by watcher or other tools to track access patterns.
    """
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = load_correlations(root)
    
    # Record with recent files (simple sliding window)
    recent_key = '_recent_accesses'
    if recent_key not in data.access_counts:
        data.access_counts[recent_key] = defaultdict(int)
    
    # Get recently accessed files (last 5)
    recent = [f for f in data.access_counts.get(recent_key, {}).keys() if f != file_path][-5:]
    
    # Record correlations
    for recent_file in recent:
        data.access_counts[file_path][recent_file] += 1
        data.access_counts[recent_file][file_path] += 1
    
    # Update recent list
    data.access_counts[recent_key][file_path] = 1
    
    save_correlations(data)


def format_correlations(file_path: str, correlations: List[Tuple[str, int, str]]) -> str:
    """Format correlation results as markdown."""
    lines = [
        f"# Correlations for {Path(file_path).name}",
        "",
    ]
    
    if not correlations:
        lines.append("No correlations found. Build patterns with `mcp learn-patterns`")
    else:
        lines.append(f"**Found:** {len(correlations)} correlated files\n")
        
        for related, strength, reason in correlations:
            lines.append(f"- `{Path(related).name}` (strength: {strength}, {reason})")
    
    return '\n'.join(lines)


def format_all_patterns(data: CorrelationData) -> str:
    """Format all learned patterns as markdown."""
    lines = [
        "# Learned Correlation Patterns",
        "",
        f"**Commits Analyzed:** {data.commits_analyzed}",
        f"**Last Updated:** {data.last_updated}",
        "",
    ]
    
    if data.learned_patterns:
        lines.append("## Discovered Patterns\n")
        for pattern in data.learned_patterns:
            lines.append(f"- {pattern}")
    else:
        lines.append("No patterns learned yet. Run `mcp learn-patterns` to analyze git history.")
    
    # Top correlations
    lines.append("\n## Top Co-Modified Files\n")
    
    all_pairs = []
    seen = set()
    for f1, others in data.comod_counts.items():
        for f2, count in others.items():
            if count >= 3:  # Minimum threshold
                key = tuple(sorted([f1, f2]))
                if key not in seen:
                    seen.add(key)
                    all_pairs.append((f1, f2, count))
    
    all_pairs.sort(key=lambda x: x[2], reverse=True)
    
    for f1, f2, count in all_pairs[:15]:
        lines.append(f"- `{Path(f1).name}` <-> `{Path(f2).name}` ({count}x)")
    
    return '\n'.join(lines)


def main():
    """CLI entry point."""
    Console.header("Correlation Tracker")
    
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    root = get_project_boundary() or find_project_root() or Path.cwd()
    
    # Learn patterns from git
    if '--learn' in sys.argv or 'learn-patterns' in ' '.join(sys.argv):
        data = analyze_git_history(root)
        print(format_all_patterns(data))
        return 0
    
    # Show correlations for specific file
    if args:
        file_query = args[0]
        data = load_correlations(root)
        correlations = get_correlations_for_file(file_query, data)
        print(format_correlations(file_query, correlations))
        return 0
    
    # Show all patterns
    data = load_correlations(root)
    print(format_all_patterns(data))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Predictive Context Loader
=========================
Predict what files an AI agent will need based on task description.

Pre-bundles context BEFORE the agent starts working, enabling
instant context loading with zero latency.

Usage:
    python mcp.py predict-context "implement user authentication"
    python mcp.py predict-context "fix bug in login flow"
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Set, Optional

from .utils import (
    find_python_files,
    find_project_root,
    get_project_boundary,
    Console
)


@dataclass
class PredictedContext:
    """Pre-bundled context for a task."""
    task: str
    predicted_files: List[str] = field(default_factory=list)
    predicted_functions: List[str] = field(default_factory=list)
    skeleton_snippets: Dict[str, str] = field(default_factory=dict)
    related_tests: List[str] = field(default_factory=list)
    confidence: float = 0.0


def extract_task_keywords(task: str) -> List[str]:
    """Extract meaningful keywords from task description."""
    # Common words to skip
    skip_words = {
        'the', 'a', 'an', 'to', 'for', 'in', 'on', 'at', 'and', 'or', 'is',
        'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
        'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
        'might', 'must', 'shall', 'can', 'need', 'implement', 'fix', 'add',
        'update', 'modify', 'change', 'create', 'delete', 'remove', 'bug',
        'issue', 'problem', 'error', 'make', 'get', 'set', 'with', 'from'
    }
    
    words = task.lower().split()
    keywords = []
    
    for word in words:
        # Clean word
        clean = ''.join(c for c in word if c.isalnum() or c == '_')
        if len(clean) > 2 and clean not in skip_words:
            keywords.append(clean)
    
    return keywords[:10]  # Limit to 10 keywords


def predict_files_from_graph(keywords: List[str], root: Path) -> Set[str]:
    """Use call graph to find related files."""
    related = set()
    
    try:
        from .call_graph import load_call_graph, query_graph
        graph = load_call_graph(root)
        
        if graph:
            for keyword in keywords:
                result = query_graph(graph, keyword)
                related.update(result.get('related_files', []))
    except Exception:
        pass
    
    return related


def predict_files_from_search(keywords: List[str], root: Path) -> Set[str]:
    """Use semantic search to find related files."""
    related = set()
    
    try:
        from .vector_store import VectorStore
        store = VectorStore()
        
        query = ' '.join(keywords)
        results = store.search(query, limit=10)
        
        for result in results:
            if hasattr(result, 'file'):
                related.add(result.file)
    except Exception:
        pass
    
    return related


def predict_files_from_names(keywords: List[str], root: Path) -> Set[str]:
    """Find files with matching names."""
    related = set()
    
    for path in find_python_files(root):
        name_lower = path.name.lower()
        stem_lower = path.stem.lower()
        
        for keyword in keywords:
            if keyword in name_lower or keyword in stem_lower:
                related.add(str(path))
                break
    
    return related


def find_related_tests(files: Set[str], root: Path) -> List[str]:
    """Find test files related to predicted files."""
    tests = []
    
    for file_path in files:
        path = Path(file_path)
        # Look for test_<name>.py or <name>_test.py
        test_patterns = [
            f"test_{path.stem}.py",
            f"{path.stem}_test.py",
            f"tests/test_{path.stem}.py",
            f"test/test_{path.stem}.py"
        ]
        
        for pattern in test_patterns:
            test_path = root / pattern
            if test_path.exists():
                tests.append(str(test_path))
                break
    
    return tests


def generate_skeleton_snippets(files: Set[str], max_per_file: int = 500) -> Dict[str, str]:
    """Generate skeleton snippets for predicted files."""
    snippets = {}
    
    try:
        from .skeleton import generate_file_skeleton, format_file_skeleton
        
        for file_path in list(files)[:10]:  # Limit to 10 files
            path = Path(file_path)
            if path.exists() and path.suffix == '.py':
                skeleton = generate_file_skeleton(path)
                if skeleton:
                    formatted = format_file_skeleton(skeleton, include_imports=False)
                    snippets[file_path] = formatted[:max_per_file]
    except Exception:
        pass
    
    return snippets


def predict_context(task: str, root: Path = None) -> PredictedContext:
    """
    Predict context needed for a task.
    
    Combines multiple strategies:
    1. Keyword extraction from task
    2. Call graph queries
    3. Semantic search
    4. Filename matching
    """
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    
    Console.info(f"Predicting context for: {task}")
    
    # Extract keywords
    keywords = extract_task_keywords(task)
    Console.info(f"Keywords: {', '.join(keywords)}")
    
    # Gather predictions from multiple sources
    all_files: Set[str] = set()
    
    # Method 1: Call graph (highest confidence)
    graph_files = predict_files_from_graph(keywords, root)
    all_files.update(graph_files)
    
    # Method 2: Semantic search
    search_files = predict_files_from_search(keywords, root)
    all_files.update(search_files)
    
    # Method 3: Filename matching
    name_files = predict_files_from_names(keywords, root)
    all_files.update(name_files)
    
    # Find related tests
    tests = find_related_tests(all_files, root)
    
    # Generate skeletons
    skeletons = generate_skeleton_snippets(all_files)
    
    # Calculate confidence based on overlap
    confidence = 0.0
    if all_files:
        overlap_count = len(graph_files & search_files) + len(graph_files & name_files)
        confidence = min(0.9, 0.3 + (overlap_count * 0.1))
    
    Console.ok(f"Predicted {len(all_files)} files, {len(tests)} tests")
    
    return PredictedContext(
        task=task,
        predicted_files=sorted(all_files)[:20],
        predicted_functions=[],  # Could extract from skeletons
        skeleton_snippets=skeletons,
        related_tests=tests,
        confidence=confidence
    )


def format_predicted_context(ctx: PredictedContext) -> str:
    """Format predicted context as markdown."""
    lines = [
        f"# Predicted Context for: {ctx.task}",
        f"",
        f"**Confidence:** {ctx.confidence:.0%}",
        f"**Files:** {len(ctx.predicted_files)}",
        f"**Tests:** {len(ctx.related_tests)}",
        "",
    ]
    
    if ctx.predicted_files:
        lines.append("## Predicted Files")
        for f in ctx.predicted_files[:10]:
            lines.append(f"- `{f}`")
        if len(ctx.predicted_files) > 10:
            lines.append(f"- ... and {len(ctx.predicted_files) - 10} more")
        lines.append("")
    
    if ctx.related_tests:
        lines.append("## Related Tests")
        for t in ctx.related_tests[:5]:
            lines.append(f"- `{t}`")
        lines.append("")
    
    if ctx.skeleton_snippets:
        lines.append("## Code Skeletons")
        for path, skeleton in list(ctx.skeleton_snippets.items())[:5]:
            lines.append(f"### {Path(path).name}")
            lines.append("```python")
            lines.append(skeleton)
            lines.append("```")
            lines.append("")
    
    return '\n'.join(lines)


def main():
    """CLI entry point."""
    Console.header("Predictive Context Loader")
    
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    
    if not args:
        Console.fail("Usage: mcp predict-context \"task description\"")
        print("\nExamples:")
        print('  mcp predict-context "implement user authentication"')
        print('  mcp predict-context "fix login timeout bug"')
        return 1
    
    task = ' '.join(args)
    root = get_project_boundary() or find_project_root() or Path.cwd()
    
    ctx = predict_context(task, root)
    print(format_predicted_context(ctx))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

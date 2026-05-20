"""
Auto-Healing Error Analyzer
===========================
Analyze errors, suggest fixes, and automatically learn from mistakes.

When code fails:
1. Captures the error pattern
2. Matches against known fixes
3. Suggests solutions
4. Auto-appends lesson to lessons_learned.md

Usage:
    python mcp.py heal                    # Analyze last error
    python mcp.py heal "error message"    # Analyze specific error
    python mcp.py heal --learn "lesson"   # Manually add lesson
"""

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from .utils import (
    find_project_root,
    get_project_boundary,
    Console
)


@dataclass
class ErrorPattern:
    """A known error pattern and its fix."""
    pattern: str  # Regex pattern to match
    category: str  # e.g., 'ImportError', 'TypeError', 'SyntaxError'
    description: str
    fix: str
    example: str = ""
    occurrences: int = 0
    last_seen: str = ""


@dataclass
class ErrorAnalysis:
    """Result of analyzing an error."""
    error_text: str
    category: str
    matched_pattern: Optional[ErrorPattern]
    suggested_fix: str
    confidence: float
    related_files: List[str] = field(default_factory=list)


# Built-in error patterns with fixes
BUILTIN_PATTERNS = [
    ErrorPattern(
        pattern=r"ModuleNotFoundError: No module named '(\w+)'",
        category="ImportError",
        description="Missing module import",
        fix="Install missing package: pip install {match}",
        example="ModuleNotFoundError: No module named 'requests'"
    ),
    ErrorPattern(
        pattern=r"ImportError: cannot import name '(\w+)' from '(\w+)'",
        category="ImportError",
        description="Cannot import specific name from module",
        fix="Check if '{match}' exists in '{match2}'. May need to update import path or install package.",
    ),
    ErrorPattern(
        pattern=r"TypeError: (\w+)\(\) got an unexpected keyword argument '(\w+)'",
        category="TypeError",
        description="Unexpected keyword argument",
        fix="Remove '{match2}' argument from call to {match}(), or check function signature.",
    ),
    ErrorPattern(
        pattern=r"TypeError: (\w+)\(\) missing (\d+) required positional argument",
        category="TypeError",
        description="Missing required argument",
        fix="Add {match2} missing argument(s) to {match}() call.",
    ),
    ErrorPattern(
        pattern=r"AttributeError: '(\w+)' object has no attribute '(\w+)'",
        category="AttributeError",
        description="Object missing attribute",
        fix="'{match}' objects don't have '{match2}'. Check for typos or use correct attribute name.",
    ),
    ErrorPattern(
        pattern=r"NameError: name '(\w+)' is not defined",
        category="NameError",
        description="Undefined name",
        fix="'{match}' is not defined. Add import or define variable before use.",
    ),
    ErrorPattern(
        pattern=r"SyntaxError: invalid syntax",
        category="SyntaxError",
        description="Invalid Python syntax",
        fix="Check for missing colons, parentheses, brackets, or quotes on the line.",
    ),
    ErrorPattern(
        pattern=r"IndentationError: (expected an indented block|unexpected indent)",
        category="IndentationError",
        description="Indentation problem",
        fix="Fix indentation. Use consistent 4-space indentation.",
    ),
    ErrorPattern(
        pattern=r"FileNotFoundError: \[Errno 2\] No such file or directory: '(.+)'",
        category="FileNotFoundError",
        description="File not found",
        fix="File '{match}' doesn't exist. Check path or create the file.",
    ),
    ErrorPattern(
        pattern=r"KeyError: '(\w+)'",
        category="KeyError",
        description="Missing dictionary key",
        fix="Key '{match}' not in dictionary. Use .get('{match}', default) or check if key exists.",
    ),
    ErrorPattern(
        pattern=r"ValueError: (.+)",
        category="ValueError",
        description="Invalid value",
        fix="Value error: {match}. Check that input values are valid for the operation.",
    ),
    ErrorPattern(
        pattern=r"AssertionError",
        category="AssertionError",
        description="Assertion failed",
        fix="An assert statement failed. Check test conditions or debug assertion.",
    ),
    ErrorPattern(
        pattern=r"RecursionError: maximum recursion depth exceeded",
        category="RecursionError",
        description="Infinite recursion",
        fix="Function is calling itself infinitely. Add base case or use iteration instead.",
    ),
]


def get_patterns_path(root: Path) -> Path:
    """Get path to custom error patterns file."""
    return root / '.mcp' / 'error_patterns.json'


def get_lessons_path(root: Path) -> Path:
    """Get path to lessons learned file."""
    return root / '.mcp' / 'lessons_learned.md'


def load_custom_patterns(root: Path) -> List[ErrorPattern]:
    """Load custom error patterns from project."""
    patterns_path = get_patterns_path(root)
    
    if patterns_path.exists():
        try:
            with open(patterns_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return [ErrorPattern(**p) for p in data]
        except Exception:
            pass
    
    return []


def save_custom_patterns(patterns: List[ErrorPattern], root: Path):
    """Save custom error patterns."""
    patterns_path = get_patterns_path(root)
    patterns_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(patterns_path, 'w', encoding='utf-8') as f:
        json.dump([asdict(p) for p in patterns], f, indent=2)


def analyze_error(error_text: str, root: Path = None) -> ErrorAnalysis:
    """
    Analyze an error and suggest a fix.
    
    Combines built-in patterns with project-specific learned patterns.
    """
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    
    # Combine built-in and custom patterns
    all_patterns = BUILTIN_PATTERNS + load_custom_patterns(root)
    
    # Try to match patterns
    for pattern in all_patterns:
        match = re.search(pattern.pattern, error_text)
        if match:
            # Build fix with captured groups
            fix = pattern.fix
            for i, group in enumerate(match.groups()):
                fix = fix.replace(f"{{match{i+1 if i > 0 else ''}}}", group)
                fix = fix.replace(f"{{match}}", group)  # First group as default
            
            return ErrorAnalysis(
                error_text=error_text,
                category=pattern.category,
                matched_pattern=pattern,
                suggested_fix=fix,
                confidence=0.8 if pattern in BUILTIN_PATTERNS else 0.9
            )
    
    # No pattern matched - generic analysis
    category = "Unknown"
    if "Error:" in error_text:
        # Try to extract error type
        error_match = re.search(r'(\w+Error):', error_text)
        if error_match:
            category = error_match.group(1)
    
    return ErrorAnalysis(
        error_text=error_text,
        category=category,
        matched_pattern=None,
        suggested_fix="No specific fix found. Review the error message and traceback.",
        confidence=0.3
    )


def add_lesson(lesson: str, root: Path = None):
    """Add a lesson to lessons_learned.md."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    lessons_path = get_lessons_path(root)
    lessons_path.parent.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d")
    lesson_line = f"- {lesson} (learned: {timestamp})\n"
    
    # Load existing or create new
    if lessons_path.exists():
        content = lessons_path.read_text(encoding='utf-8')
        if lesson in content:
            Console.warn("Lesson already recorded")
            return
    else:
        content = "# Lessons Learned\n\n> These are injected into every AI agent context\n\n"
    
    # Append lesson
    content += lesson_line
    lessons_path.write_text(content, encoding='utf-8')
    Console.ok(f"Learned: {lesson}")


def format_analysis(analysis: ErrorAnalysis) -> str:
    """Format error analysis as readable text."""
    lines = [
        f"# Error Analysis",
        "",
        f"**Category:** {analysis.category}",
        f"**Confidence:** {analysis.confidence:.0%}",
        "",
        "## Error",
        "```",
        analysis.error_text[:500],
        "```",
        "",
        "## Suggested Fix",
        analysis.suggested_fix,
        "",
    ]
    
    if analysis.matched_pattern:
        lines.extend([
            "## Pattern Matched",
            f"- {analysis.matched_pattern.description}",
        ])
    
    return '\n'.join(lines)


def main():
    """CLI entry point."""
    Console.header("Auto-Healing Error Analyzer")
    
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    root = get_project_boundary() or find_project_root() or Path.cwd()
    
    # Add lesson
    for i, arg in enumerate(sys.argv):
        if arg == '--learn' and i + 1 < len(sys.argv):
            lesson = sys.argv[i + 1]
            add_lesson(lesson, root)
            return 0
    
    # List lessons
    if '--lessons' in sys.argv:
        lessons_path = get_lessons_path(root)
        if lessons_path.exists():
            print(lessons_path.read_text(encoding='utf-8'))
        else:
            Console.info("No lessons learned yet. Use --learn to add one.")
        return 0
    
    # Analyze error
    if args:
        error_text = ' '.join(args)
    else:
        Console.info("Paste error text (Ctrl+Z or Ctrl+D to finish):")
        try:
            error_text = sys.stdin.read()
        except KeyboardInterrupt:
            return 0
    
    if not error_text.strip():
        Console.fail("No error text provided")
        return 1
    
    analysis = analyze_error(error_text, root)
    print(format_analysis(analysis))
    
    # Offer to learn
    if analysis.confidence < 0.5:
        Console.info("\nTip: Use 'mcp heal --learn \"lesson\"' to add custom lessons")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

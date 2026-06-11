"""
Skeleton Views
==============
Signature-only compressed views of files or directories - the fastest way
for an agent to absorb a module's shape without reading function bodies.
Works for every language treesitter_utils can parse, including the regex
fallback (TypeScript/JavaScript/Python and more) when tree-sitter grammars
are not installed.

Usage:
    python mcp.py skeleton <path> [--budget N]
"""

from pathlib import Path
import sys

from .treesitter_utils import parse_file
from .utils import Console, find_source_files, find_project_root

DEFAULT_BUDGET_CHARS = 20000


def skeleton_for_file(path: Path) -> str:
    """One file's signature-only view."""
    parsed = parse_file(Path(path))
    lines = [f"# {path} ({parsed.language or 'unknown'})"]
    if parsed.error:
        lines.append(f"  [unparsed: {parsed.error}]")
        return "\n".join(lines)

    for imp in parsed.imports[:20]:
        lines.append(f"  import {imp}")

    for cls in parsed.classes:
        doc = f" - {cls.docstring.splitlines()[0]}" if cls.docstring else ""
        lines.append(f"  class {cls.name}{doc}  [L{cls.line_start}-{cls.line_end}]")
        for member in cls.children:
            sig = member.signature or member.name
            lines.append(f"    {sig}  [L{member.line_start}]")

    for fn in parsed.functions:
        sig = fn.signature or fn.name
        doc = f" - {fn.docstring.splitlines()[0]}" if fn.docstring else ""
        lines.append(f"  {sig}{doc}  [L{fn.line_start}-{fn.line_end}]")

    if len(lines) == 1:
        lines.append("  (no functions or classes found)")
    return "\n".join(lines)


def skeleton(path: Path, budget_chars: int = DEFAULT_BUDGET_CHARS) -> str:
    """Signature-only view of a file or an entire directory tree."""
    path = Path(path)
    if path.is_file():
        return skeleton_for_file(path)

    sections = []
    used = 0
    for f in find_source_files(path):
        section = skeleton_for_file(f)
        if used + len(section) > budget_chars:
            sections.append(
                "[TRUNCATED] Skeleton exceeded %d chars - narrow the path "
                "or raise --budget N." % budget_chars)
            break
        sections.append(section)
        used += len(section)
    if not sections:
        return "(no source files found under %s)" % path
    return "\n\n".join(sections)


def _parse_budget(argv):
    """Extract --budget N, returning (budget, argv without the flag pair)."""
    budget = DEFAULT_BUDGET_CHARS
    argv = list(argv)
    while '--budget' in argv:
        i = argv.index('--budget')
        if i + 1 < len(argv):
            try:
                budget = max(1000, int(argv[i + 1]))
            except ValueError:
                pass
            del argv[i:i + 2]
        else:
            del argv[i]
    return budget, argv


def main():
    """CLI entry point."""
    Console.header("Skeleton View")

    budget, argv_rest = _parse_budget(sys.argv[1:])
    args = [a for a in argv_rest if not a.startswith('-')]

    if args:
        target = Path(args[0])
    else:
        target = find_project_root() or Path.cwd()

    if not target.exists():
        Console.fail(f"Path not found: {target}")
        return 1

    print(skeleton(target, budget))
    return 0


if __name__ == "__main__":
    sys.exit(main())

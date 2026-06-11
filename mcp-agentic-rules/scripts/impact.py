"""
Impact Analysis
================
Analyze what breaks when code changes.

Usage:
    python mcp.py impact [file]
    python mcp.py impact --test [file]  # Show affected tests
"""

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import ast
import json
import re
import sys

from .utils import Console, find_python_files, find_project_root, find_source_files

JS_EXTS = {'.ts', '.tsx', '.js', '.jsx', '.mts', '.cts', '.mjs', '.cjs'}
RESOLVE_EXTS = ['', '.ts', '.tsx', '.js', '.jsx', '.mts', '.cts', '.mjs', '.cjs']

# import/export ... from 'spec'  |  import 'spec'  |  require('spec')  |  import('spec')
JS_IMPORT_RE = re.compile(
    r"(?:\bimport|\bexport)\s+(?:[^'\";]*?\bfrom\s+)?['\"]([^'\"]+)['\"]"
    r"|\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)"
    r"|\bimport\(\s*['\"]([^'\"]+)['\"]\s*\)")


def parse_workspace_packages(root: Path) -> Dict[str, Path]:
    """
    Map workspace package names to their directories using pnpm-workspace.yaml
    globs and/or the package.json "workspaces" field.
    """
    root = Path(root)
    patterns: List[str] = []

    ws = root / 'pnpm-workspace.yaml'
    if ws.exists():
        try:
            for line in ws.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line.startswith('- '):
                    pattern = line[2:].strip().strip('\'"')
                    if pattern and not pattern.startswith('!'):
                        patterns.append(pattern)
        except Exception:
            pass

    pkg = root / 'package.json'
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding='utf-8'))
            workspaces = data.get('workspaces')
            if isinstance(workspaces, list):
                patterns.extend(workspaces)
            elif isinstance(workspaces, dict):
                patterns.extend(workspaces.get('packages', []))
        except Exception:
            pass

    mapping: Dict[str, Path] = {}
    for pattern in patterns:
        try:
            for d in root.glob(pattern):
                pj = d / 'package.json'
                if pj.exists():
                    try:
                        name = json.loads(pj.read_text(encoding='utf-8')).get('name')
                        if name:
                            mapping[name] = d
                    except Exception:
                        pass
        except (ValueError, OSError):
            pass
    return mapping


def resolve_js_import(spec: str, file_path: Path, root: Path,
                      workspace_map: Dict[str, Path]) -> Optional[str]:
    """
    Resolve a JS/TS import specifier to a repo-relative file key, or None
    for external packages. Handles relative imports (with extension and
    /index fallbacks) and pnpm workspace package names incl. subpaths.
    """
    candidates: List[Path] = []
    if spec.startswith('.'):
        candidates.append((file_path.parent / spec))
    else:
        parts = spec.split('/')
        matched = None
        for take in (2, 1):  # scoped names (@org/pkg) consume two segments
            name = '/'.join(parts[:take])
            if name in workspace_map:
                matched = (name, '/'.join(parts[take:]))
                break
        if not matched:
            return None
        name, sub = matched
        base_dir = workspace_map[name]
        if sub:
            candidates.append(base_dir / sub)
        else:
            candidates.append(base_dir / 'src' / 'index')
            candidates.append(base_dir / 'index')
            try:
                main = json.loads(
                    (base_dir / 'package.json').read_text(encoding='utf-8')).get('main')
                if main:
                    candidates.append(base_dir / main)
            except Exception:
                pass

    for cand in candidates:
        for ext in RESOLVE_EXTS:
            p = Path(str(cand) + ext)
            if p.is_file():
                try:
                    return str(p.resolve().relative_to(Path(root).resolve()))
                except ValueError:
                    return None
        for ext in RESOLVE_EXTS[1:]:
            p = cand / ('index' + ext)
            if p.is_file():
                try:
                    return str(p.resolve().relative_to(Path(root).resolve()))
                except ValueError:
                    return None
    return None


@dataclass
class ImpactReport:
    """Report of change impact."""
    file: str
    direct_dependents: List[str] = field(default_factory=list)  # Files that import this
    indirect_dependents: List[str] = field(default_factory=list)  # Transitive deps
    affected_tests: List[str] = field(default_factory=list)
    total_impact: int = 0

    def to_markdown(self) -> str:
        lines = [
            f"# Impact Report: {Path(self.file).name}",
            "",
            f"**Total Impact:** {self.total_impact} files",
            "",
        ]

        if self.direct_dependents:
            lines.append("## Direct Dependents")
            for dep in self.direct_dependents[:10]:
                lines.append(f"- {dep}")
            lines.append("")

        if self.indirect_dependents:
            lines.append("## Indirect Dependents")
            for dep in self.indirect_dependents[:10]:
                lines.append(f"- {dep}")
            lines.append("")

        if self.affected_tests:
            lines.append("## Affected Tests")
            for test in self.affected_tests[:10]:
                lines.append(f"- {test}")

        return '\n'.join(lines)


class DependencyGraph:
    """Graph of file dependencies."""

    def __init__(self):
        self.imports: Dict[str, Set[str]] = defaultdict(set)  # file -> what it imports
        self.imported_by: Dict[str, Set[str]] = defaultdict(set)  # file -> who imports it
        self.module_to_file: Dict[str, str] = {}  # module name -> file path
        self.all_files: Set[str] = set()  # every file key seen during build

    def add_file(self, file_path: Path, root: Path,
                 workspace_map: Dict[str, Path] = None):
        """Add a file's imports to the graph (Python via ast, JS/TS via regex)."""
        file_key = str(file_path.relative_to(root))
        suffix = file_path.suffix.lower()

        if suffix in JS_EXTS:
            self.all_files.add(file_key)
            self._add_js_file(file_path, root, file_key, workspace_map or {})
            return

        if suffix not in ('.py', '.pyi'):
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source)
        except Exception:
            return

        self.all_files.add(file_key)

        # Register this module
        module_name = str(file_path.relative_to(root).with_suffix('')).replace('\\', '.').replace('/', '.')
        self.module_to_file[module_name] = file_key

        # Extract imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[file_key].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.imports[file_key].add(node.module)

    def _add_js_file(self, file_path: Path, root: Path, file_key: str,
                     workspace_map: Dict[str, Path]):
        """Extract and resolve JS/TS import specifiers."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
        except Exception:
            return

        for match in JS_IMPORT_RE.finditer(source):
            spec = match.group(1) or match.group(2) or match.group(3)
            if not spec:
                continue
            resolved = resolve_js_import(spec, file_path, root, workspace_map)
            if resolved:
                self.imports[file_key].add(resolved)

    def build(self, root: Path, exclude_patterns: List[str] = None):
        """Build full dependency graph for Python and JS/TS sources."""
        workspace_map = parse_workspace_packages(root)
        if workspace_map:
            Console.info(f"Workspace packages: {', '.join(sorted(workspace_map))}")
        extra = set(exclude_patterns) if exclude_patterns else None
        for file_path in find_source_files(root, exclude_dirs=extra):
            self.add_file(file_path, root, workspace_map)

        # Build reverse mapping: Python imports resolve via module names,
        # JS/TS imports are already repo-relative file keys.
        for file_key, imports in self.imports.items():
            for imp in imports:
                if imp in self.module_to_file:
                    self.imported_by[self.module_to_file[imp]].add(file_key)
                elif imp in self.all_files:
                    self.imported_by[imp].add(file_key)

    def get_dependents(self, file_path: str) -> Set[str]:
        """Get files that depend on this file."""
        return self.imported_by.get(file_path, set())

    def get_dependencies(self, file_path: str) -> Set[str]:
        """Get files this file depends on."""
        return self.imports.get(file_path, set())

    def get_transitive_dependents(self, file_path: str, visited: Set[str] = None) -> Set[str]:
        """Get all transitive dependents."""
        if visited is None:
            visited = set()

        if file_path in visited:
            return set()

        visited.add(file_path)

        all_deps = set()
        direct = self.get_dependents(file_path)
        all_deps.update(direct)

        for dep in direct:
            all_deps.update(self.get_transitive_dependents(dep, visited))

        return all_deps


def build_dependency_graph(root: Path = None) -> DependencyGraph:
    """Build and return dependency graph."""
    root = root or find_project_root() or Path.cwd()

    Console.info("Building dependency graph...")

    graph = DependencyGraph()
    exclude = ['node_modules', 'venv', '.venv', '__pycache__', '.git', 'vendor']
    graph.build(root, exclude)

    Console.ok(f"Indexed {len(graph.imports)} files")

    return graph


def analyze_impact(file_path: Path, root: Path = None) -> ImpactReport:
    """Analyze impact of changing a file."""
    root = root or find_project_root() or Path.cwd()

    graph = build_dependency_graph(root)

    try:
        file_key = str(file_path.relative_to(root))
    except ValueError:
        file_key = str(file_path)

    direct = list(graph.get_dependents(file_key))

    all_deps = graph.get_transitive_dependents(file_key)
    indirect = [d for d in all_deps if d not in direct]

    # Find affected tests
    tests = [d for d in all_deps if 'test' in d.lower() or d.startswith('tests/')]

    return ImpactReport(
        file=file_key,
        direct_dependents=direct,
        indirect_dependents=indirect,
        affected_tests=tests,
        total_impact=len(all_deps)
    )


def save_impact_graph(root: Path = None):
    """Save dependency graph to disk."""
    root = root or find_project_root() or Path.cwd()

    graph = build_dependency_graph(root)

    # Convert to serializable format
    data = {
        "imports": {k: list(v) for k, v in graph.imports.items()},
        "imported_by": {k: list(v) for k, v in graph.imported_by.items()},
        "file_count": len(graph.imports)
    }

    index_path = root / '.mcp' / 'impact_graph.json'
    index_path.parent.mkdir(parents=True, exist_ok=True)

    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    Console.ok(f"Saved impact graph to {index_path}")


def main():
    """CLI entry point."""
    Console.header("Impact Analysis")

    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    root = find_project_root() or Path.cwd()

    if '--index' in sys.argv:
        save_impact_graph(root)
        return 0

    if not args:
        Console.info("Usage: python impact.py <file>")
        Console.info("Options:")
        Console.info("  --index    Save dependency graph")
        Console.info("  --test     Show only affected tests")
        return 1

    file_path = Path(args[0])

    if not file_path.exists():
        Console.fail(f"File not found: {file_path}")
        return 1

    report = analyze_impact(file_path, root)

    if '--test' in sys.argv:
        Console.info(f"Affected tests for {file_path.name}:")
        for test in report.affected_tests:
            print(f"  - {test}")
        print(f"\nTotal: {len(report.affected_tests)} tests")
    else:
        print(report.to_markdown())

    return 0


if __name__ == "__main__":
    sys.exit(main())

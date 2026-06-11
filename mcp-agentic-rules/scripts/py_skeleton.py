"""
Code Skeleton Generator
=======================
Generate signature-only "skeleton" views of code files for AI agents.

Compresses large codebases by keeping only:
- Class and function signatures
- Docstrings and type hints
- Decorators and inheritance
- Replacing implementation bodies with `...`

Usage:
    python mcp.py skeleton [path]           # Generate skeleton for file/directory
    python mcp.py skeleton src/ --output    # Write to SKELETON.md
"""

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from .utils import (
    find_python_files,
    find_project_root,
    get_project_boundary,
    Console
)


@dataclass
class SkeletonItem:
    """A skeleton item (class, function, etc)."""
    name: str
    item_type: str  # 'class', 'function', 'method'
    signature: str
    docstring: Optional[str]
    line_start: int
    line_end: int
    decorators: List[str] = field(default_factory=list)
    children: List['SkeletonItem'] = field(default_factory=list)


@dataclass
class FileSkeleton:
    """Skeleton of a single file."""
    path: Path
    module_docstring: Optional[str]
    imports: List[str] = field(default_factory=list)
    items: List[SkeletonItem] = field(default_factory=list)
    original_lines: int = 0
    skeleton_lines: int = 0


@dataclass
class CodebaseSkeleton:
    """Skeleton of entire codebase."""
    root: Path
    files: List[FileSkeleton] = field(default_factory=list)
    total_original_lines: int = 0
    total_skeleton_lines: int = 0
    compression_ratio: float = 0.0


def get_decorator_string(decorator: ast.expr) -> str:
    """Convert decorator AST node to string."""
    try:
        if hasattr(ast, 'unparse'):
            return '@' + ast.unparse(decorator)
        elif isinstance(decorator, ast.Name):
            return '@' + decorator.id
        elif isinstance(decorator, ast.Attribute):
            return '@' + decorator.attr
        elif isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                return '@' + decorator.func.id
            elif isinstance(decorator.func, ast.Attribute):
                return '@' + decorator.func.attr
        return '@...'
    except Exception:
        return '@...'


def get_type_annotation_string(node: Optional[ast.expr]) -> str:
    """Convert type annotation to string."""
    if node is None:
        return ''
    try:
        if hasattr(ast, 'unparse'):
            return ast.unparse(node)
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Constant):
            return repr(node.value)
        elif isinstance(node, ast.Subscript):
            return f"{get_type_annotation_string(node.value)}[...]"
        return '...'
    except Exception:
        return '...'


def build_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build function signature string."""
    # Handle async
    prefix = 'async ' if isinstance(node, ast.AsyncFunctionDef) else ''
    
    # Build arguments
    args_parts = []
    
    # Regular args
    defaults_offset = len(node.args.args) - len(node.args.defaults)
    for i, arg in enumerate(node.args.args):
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f': {get_type_annotation_string(arg.annotation)}'
        
        # Check for default
        default_idx = i - defaults_offset
        if default_idx >= 0 and default_idx < len(node.args.defaults):
            try:
                if hasattr(ast, 'unparse'):
                    default_val = ast.unparse(node.args.defaults[default_idx])
                    # Truncate long defaults
                    if len(default_val) > 20:
                        default_val = '...'
                    arg_str += f' = {default_val}'
                else:
                    arg_str += ' = ...'
            except Exception:
                arg_str += ' = ...'
        
        args_parts.append(arg_str)
    
    # *args
    if node.args.vararg:
        vararg_str = f'*{node.args.vararg.arg}'
        if node.args.vararg.annotation:
            vararg_str += f': {get_type_annotation_string(node.args.vararg.annotation)}'
        args_parts.append(vararg_str)
    
    # **kwargs
    if node.args.kwarg:
        kwarg_str = f'**{node.args.kwarg.arg}'
        if node.args.kwarg.annotation:
            kwarg_str += f': {get_type_annotation_string(node.args.kwarg.annotation)}'
        args_parts.append(kwarg_str)
    
    args_str = ', '.join(args_parts)
    
    # Return type
    return_str = ''
    if node.returns:
        return_str = f' -> {get_type_annotation_string(node.returns)}'
    
    return f'{prefix}def {node.name}({args_str}){return_str}'


def build_class_signature(node: ast.ClassDef) -> str:
    """Build class signature string."""
    bases = []
    for base in node.bases:
        bases.append(get_type_annotation_string(base))
    
    if bases:
        return f'class {node.name}({", ".join(bases)})'
    return f'class {node.name}'


def extract_function_skeleton(node: ast.FunctionDef | ast.AsyncFunctionDef) -> SkeletonItem:
    """Extract skeleton from function."""
    decorators = [get_decorator_string(d) for d in node.decorator_list]
    signature = build_function_signature(node)
    docstring = ast.get_docstring(node)
    
    return SkeletonItem(
        name=node.name,
        item_type='function',
        signature=signature,
        docstring=docstring,
        line_start=node.lineno,
        line_end=node.end_lineno or node.lineno,
        decorators=decorators
    )


def extract_class_skeleton(node: ast.ClassDef) -> SkeletonItem:
    """Extract skeleton from class."""
    decorators = [get_decorator_string(d) for d in node.decorator_list]
    signature = build_class_signature(node)
    docstring = ast.get_docstring(node)
    
    # Extract methods
    methods = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method = extract_function_skeleton(item)
            method.item_type = 'method'
            methods.append(method)
    
    return SkeletonItem(
        name=node.name,
        item_type='class',
        signature=signature,
        docstring=docstring,
        line_start=node.lineno,
        line_end=node.end_lineno or node.lineno,
        decorators=decorators,
        children=methods
    )


def generate_file_skeleton(path: Path) -> Optional[FileSkeleton]:
    """Generate skeleton for a single Python file."""
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            source = f.read()
    except Exception as e:
        Console.warn(f"Could not read {path}: {e}")
        return None
    
    original_lines = source.count('\n') + 1
    
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        Console.warn(f"Syntax error in {path}: {e}")
        return None
    
    skeleton = FileSkeleton(
        path=path,
        module_docstring=ast.get_docstring(tree),
        original_lines=original_lines
    )
    
    # Extract imports
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                skeleton.imports.append(f'import {alias.name}')
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names = ', '.join(a.name for a in node.names[:5])
                if len(node.names) > 5:
                    names += ', ...'
                skeleton.imports.append(f'from {node.module} import {names}')
    
    # Extract classes and functions
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            skeleton.items.append(extract_class_skeleton(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            skeleton.items.append(extract_function_skeleton(node))
    
    return skeleton


def format_skeleton_item(item: SkeletonItem, indent: str = '') -> List[str]:
    """Format a skeleton item as code lines."""
    lines = []
    
    # Decorators
    for dec in item.decorators:
        lines.append(f'{indent}{dec}')
    
    # Signature
    lines.append(f'{indent}{item.signature}:')
    
    # Docstring
    if item.docstring:
        # Single line or multi-line docstring
        doc_lines = item.docstring.split('\n')
        if len(doc_lines) == 1 and len(doc_lines[0]) < 60:
            lines.append(f'{indent}    """{doc_lines[0]}"""')
        else:
            lines.append(f'{indent}    """')
            for doc_line in doc_lines[:5]:  # Limit to 5 lines
                lines.append(f'{indent}    {doc_line}')
            if len(doc_lines) > 5:
                lines.append(f'{indent}    ...')
            lines.append(f'{indent}    """')
    
    # Children (methods for classes)
    if item.children:
        for child in item.children:
            lines.append('')
            lines.extend(format_skeleton_item(child, indent + '    '))
    else:
        lines.append(f'{indent}    ...')
    
    return lines


def format_file_skeleton(skeleton: FileSkeleton, include_imports: bool = True) -> str:
    """Format file skeleton as Python code."""
    lines = []
    
    # Module docstring
    if skeleton.module_docstring:
        lines.append('"""')
        for line in skeleton.module_docstring.split('\n')[:5]:
            lines.append(line)
        if len(skeleton.module_docstring.split('\n')) > 5:
            lines.append('...')
        lines.append('"""')
        lines.append('')
    
    # Imports (condensed)
    if include_imports and skeleton.imports:
        for imp in skeleton.imports[:10]:
            lines.append(imp)
        if len(skeleton.imports) > 10:
            lines.append(f'# ... and {len(skeleton.imports) - 10} more imports')
        lines.append('')
    
    # Items
    for item in skeleton.items:
        lines.extend(format_skeleton_item(item))
        lines.append('')
    
    skeleton.skeleton_lines = len(lines)
    return '\n'.join(lines)


def generate_codebase_skeleton(
    root: Path,
    exclude_patterns: List[str] = None
) -> CodebaseSkeleton:
    """Generate skeleton for entire codebase."""
    root = Path(root).resolve()
    
    Console.info(f"Generating skeleton for {root}...")
    
    codebase = CodebaseSkeleton(root=root)
    
    files = list(find_python_files(root, exclude_patterns))
    Console.info(f"Found {len(files)} Python files")
    
    for path in files:
        file_skeleton = generate_file_skeleton(path)
        if file_skeleton:
            # Generate formatted content to count lines
            format_file_skeleton(file_skeleton, include_imports=False)
            codebase.files.append(file_skeleton)
            codebase.total_original_lines += file_skeleton.original_lines
            codebase.total_skeleton_lines += file_skeleton.skeleton_lines
    
    if codebase.total_original_lines > 0:
        codebase.compression_ratio = 1 - (codebase.total_skeleton_lines / codebase.total_original_lines)
    
    Console.ok(f"Generated skeletons for {len(codebase.files)} files")
    Console.info(f"Compression: {codebase.total_original_lines} -> {codebase.total_skeleton_lines} lines ({codebase.compression_ratio:.1%} reduction)")
    
    return codebase


def format_codebase_skeleton_markdown(codebase: CodebaseSkeleton) -> str:
    """Format codebase skeleton as Markdown."""
    lines = [
        "# Codebase Skeleton",
        "",
        f"**Root:** `{codebase.root}`",
        f"**Files:** {len(codebase.files)}",
        f"**Compression:** {codebase.total_original_lines} -> {codebase.total_skeleton_lines} lines ({codebase.compression_ratio:.1%} reduction)",
        "",
        "---",
        "",
    ]
    
    for file_skeleton in codebase.files:
        try:
            relative = file_skeleton.path.relative_to(codebase.root)
        except ValueError:
            relative = file_skeleton.path
        
        lines.append(f"## `{relative}`")
        lines.append("")
        lines.append("```python")
        lines.append(format_file_skeleton(file_skeleton, include_imports=False))
        lines.append("```")
        lines.append("")
    
    return '\n'.join(lines)


def get_skeleton_for_context(root: Path, max_tokens: int = 4000) -> str:
    """
    Get codebase skeleton optimized for AI context.
    
    Returns a condensed skeleton that fits within token budget.
    Prioritizes classes and top-level functions.
    """
    codebase = generate_codebase_skeleton(root)
    
    # Estimate ~4 chars per token
    max_chars = max_tokens * 4
    
    lines = [
        "# Codebase Structure",
        "",
    ]
    
    char_count = 0
    
    for file_skeleton in codebase.files:
        try:
            relative = file_skeleton.path.relative_to(codebase.root)
        except ValueError:
            relative = file_skeleton.path
        
        # File header
        header = f"\n## {relative}\n"
        
        # Just list classes and functions with signatures
        items_lines = []
        for item in file_skeleton.items:
            # Class with methods summarized
            if item.item_type == 'class':
                items_lines.append(item.signature + ':')
                if item.docstring:
                    first_line = item.docstring.split('\n')[0][:60]
                    items_lines.append(f'    """{first_line}"""')
                for method in item.children[:5]:  # Limit methods shown
                    items_lines.append(f'    {method.signature}: ...')
                if len(item.children) > 5:
                    items_lines.append(f'    # ... {len(item.children) - 5} more methods')
            else:
                items_lines.append(item.signature + ': ...')
                if item.docstring:
                    first_line = item.docstring.split('\n')[0][:60]
                    items_lines.append(f'    # {first_line}')
        
        file_content = header + '\n'.join(items_lines)
        
        if char_count + len(file_content) > max_chars:
            lines.append(f"\n# ... {len(codebase.files) - len(lines) + 2} more files truncated")
            break
        
        lines.append(file_content)
        char_count += len(file_content)
    
    return '\n'.join(lines)


def main():
    """CLI entry point."""
    Console.header("Code Skeleton Generator")
    
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    
    output_file = None
    for i, arg in enumerate(sys.argv):
        if arg == '--output' and i + 1 < len(sys.argv):
            output_file = Path(sys.argv[i + 1])
        elif arg == '--output':
            output_file = Path('SKELETON.md')
    
    # Get path
    if args:
        path = Path(args[0])
    else:
        path = get_project_boundary() or find_project_root() or Path.cwd()
    
    if not path.exists():
        Console.fail(f"Path not found: {path}")
        return 1
    
    # Single file or directory
    if path.is_file():
        skeleton = generate_file_skeleton(path)
        if skeleton:
            print(format_file_skeleton(skeleton))
            Console.ok(f"Lines: {skeleton.original_lines} -> {skeleton.skeleton_lines}")
    else:
        codebase = generate_codebase_skeleton(path)
        
        if output_file:
            markdown = format_codebase_skeleton_markdown(codebase)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(markdown)
            Console.ok(f"Written to {output_file}")
        else:
            # Print condensed version for terminal
            print(get_skeleton_for_context(path, max_tokens=2000))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

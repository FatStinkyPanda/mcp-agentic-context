"""
MCP Dynamic Context Engine
==========================
Manages context window budgets and sliding-scale chunking (Linguistic Zoom).
Provides structural skeletonization to save tokens in large codebases.
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def skeletonize_python(content: str) -> str:
    """
    Parses Python code and returns a skeleton containing classes, functions,
    docstrings, and decorators, with method/function bodies stripped.
    """
    try:
        root_node = ast.parse(content)
    except Exception:
        # Fallback to simple line filtering if parsing fails
        return _skeletonize_generic_regex(content, 'python')

    class SkeletonTransformer(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            # Keep docstring if exists
            docstring = ast.get_docstring(node)
            new_body = []
            if docstring:
                new_body.append(ast.Expr(value=ast.Constant(value=docstring)))
            # Replace function body with an ellipsis
            new_body.append(ast.Expr(value=ast.Constant(value="... [body compressed] ...")))
            node.body = new_body
            return node

        def visit_AsyncFunctionDef(self, node):
            # Same for async functions
            docstring = ast.get_docstring(node)
            new_body = []
            if docstring:
                new_body.append(ast.Expr(value=ast.Constant(value=docstring)))
            new_body.append(ast.Expr(value=ast.Constant(value="... [body compressed] ...")))
            node.body = new_body
            return node

    # Transform and unparse
    transformer = SkeletonTransformer()
    transformed_ast = transformer.visit(root_node)
    ast.fix_missing_locations(transformed_ast)
    try:
        return ast.unparse(transformed_ast)
    except Exception:
        return _skeletonize_generic_regex(content, 'python')


def _skeletonize_generic_regex(content: str, language: str) -> str:
    """
    Fallback regex-based structural skeletonizer for curly-brace and other languages.
    """
    lines = content.split('\n')
    class_pattern = None
    func_pattern = None
    comment_prefix = "//"

    if language in ('javascript', 'typescript'):
        class_pattern = re.compile(r'\b(?:class|interface)\s+([a-zA-Z_]\w*)')
        func_pattern = re.compile(r'\b(?:function\s+[a-zA-Z_]\w*|constructor|async\s+[a-zA-Z_]\w*)\s*\(|=>')
    elif language == 'go':
        class_pattern = re.compile(r'\btype\s+([a-zA-Z_]\w*)\s+(?:struct|interface)\b')
        func_pattern = re.compile(r'\bfunc\s+(?:\([^)]+\)\s+)?([a-zA-Z_]\w*)\s*\(')
    elif language == 'rust':
        class_pattern = re.compile(r'\b(?:struct|enum|trait|impl)\s+([a-zA-Z_]\w*)')
        func_pattern = re.compile(r'\bfn\s+([a-zA-Z_]\w*)')
    elif language == 'java':
        class_pattern = re.compile(r'\b(?:class|interface|enum)\s+([a-zA-Z_]\w*)')
        func_pattern = re.compile(r'\b(?:public|protected|private|static|\s)+\s+[\w<>,\[\]]+\s+([a-zA-Z_]\w*)\s*\(')
    elif language in ('c', 'cpp'):
        class_pattern = re.compile(r'\b(?:struct|class|union)\s+([a-zA-Z_]\w*)')
        func_pattern = re.compile(r'^\s*[\w:*&<>]+(?:\s+[\w:*&<>]+)*\s+([a-zA-Z_]\w*)\s*\(')
    elif language == 'python':
        class_pattern = re.compile(r'^\s*class\s+([a-zA-Z_]\w*)')
        func_pattern = re.compile(r'^\s*(?:def|async\s+def)\s+([a-zA-Z_]\w*)')
        comment_prefix = "#"

    if not class_pattern and not func_pattern:
        return "\n".join(lines[:30]) + f"\n{comment_prefix} ... [truncated] ..."

    skeleton = []
    brace_depth = 0
    in_block = False
    block_indent = ""

    for line in lines:
        stripped = line.strip()
        is_class = class_pattern.search(line) if class_pattern else False
        is_func = func_pattern.search(line) if func_pattern else False

        if is_class or is_func or stripped.startswith(('import ', 'from ', 'package ')):
            if in_block and brace_depth > 0:
                # Close out previous block
                skeleton.append(f"{block_indent}    {comment_prefix} ... [body compressed] ...")
                skeleton.append(block_indent + "}")
                in_block = False
                brace_depth = 0

            skeleton.append(line)
            if '{' in line:
                brace_depth += line.count('{') - line.count('}')
                in_block = True
                block_indent = " " * (len(line) - len(line.lstrip()))
            elif is_func and not '{' in line and language != 'python':
                # Function signature spans multiple lines or brace is on next line
                in_block = True
                brace_depth = 0
                block_indent = " " * (len(line) - len(line.lstrip()))
        else:
            if in_block:
                if '{' in line:
                    brace_depth += line.count('{') - line.count('}')
                if '}' in line:
                    brace_depth -= line.count('}')
                if brace_depth <= 0:
                    skeleton.append(f"{block_indent}    {comment_prefix} ... [body compressed] ...")
                    skeleton.append(line)
                    in_block = False
                    brace_depth = 0
            else:
                if stripped.startswith(('//', '/*', '*', '#', '"""', "'''")):
                    skeleton.append(line)

    return "\n".join(skeleton)


def skeletonize_file(path: Path, content: str) -> str:
    """
    Structural skeletonizer router that selects the correct logic based on file type.
    """
    suffix = path.suffix.lower()
    if suffix == '.py':
        return skeletonize_python(content)
    elif suffix in ('.js', '.jsx', '.ts', '.tsx'):
        return _skeletonize_generic_regex(content, 'javascript')
    elif suffix == '.go':
        return _skeletonize_generic_regex(content, 'go')
    elif suffix == '.rs':
        return _skeletonize_generic_regex(content, 'rust')
    elif suffix == '.java':
        return _skeletonize_generic_regex(content, 'java')
    elif suffix in ('.c', '.h', '.cpp', '.hpp', '.cc', '.cxx'):
        return _skeletonize_generic_regex(content, 'cpp')
    else:
        # Default simple text truncation
        lines = content.split('\n')
        if len(lines) > 40:
            return "\n".join(lines[:30]) + "\n# ... [content truncated] ..."
        return content


class ContextBudgetEngine:
    """
    Manages allocations of token budgets across context payloads,
    applying Linguistic Zoom levels to enforce limits.
    """
    def __init__(self, token_budget: int = 8000):
        self.token_budget = token_budget
        
        # Default budget partitions in fractions
        self.partitions = {
            "map": 0.05,        # 5% for Directory Graph Structure
            "activity": 0.15,   # 15% for Memories, Test Results, and Action Logs
            "active": 0.45,     # 45% for Primary Files (Open Editor + coupled targets)
            "semantic": 0.35    # 35% for Semantic vector search chunks
        }

    def get_limits(self) -> Dict[str, int]:
        """Get absolute token limits based on allocations."""
        return {k: int(self.token_budget * v) for k, v in self.partitions.items()}

    def format_and_budget_files(
        self, 
        files: List[Tuple[str, str, int]], 
        target_budget: int
    ) -> List[Tuple[str, str, int]]:
        """
        Formats files and scales down detail levels dynamically to fit the budget.
        Each file is input as a tuple: (filepath_str, content, priority_level)
        Priority level: 0 (Highest - keep full), 1 (Medium - AST skeleton), 2 (Low - summary)
        Returns: list of (filepath_str, formatted_content, token_count)
        """
        result = []
        current_tokens = 0

        # Sort files so highest priority is budgeted first
        sorted_files = sorted(files, key=lambda x: x[2])

        for path_str, raw_content, priority in sorted_files:
            path = Path(path_str)
            
            if priority == 0:
                # Level 0 Zoom: Full detail
                formatted = raw_content
                tokens = len(formatted.split())
                
                # Check budget. If tight, demote priority 0 to Level 1 AST skeleton
                if current_tokens + tokens > target_budget:
                    formatted = skeletonize_file(path, raw_content)
                    tokens = len(formatted.split())
                    priority = 1
            
            if priority == 1:
                # Level 1 Zoom: AST Skeleton
                formatted = skeletonize_file(path, raw_content)
                tokens = len(formatted.split())
                
                # Check budget. If still tight, demote to Level 2 (Summary / Truncated signature)
                if current_tokens + tokens > target_budget:
                    lines = formatted.split('\n')
                    formatted = "\n".join(lines[:15]) + "\n# ... [collapsed for budget] ..."
                    tokens = len(formatted.split())
                    priority = 2

            if priority == 2:
                # Level 2 Zoom: Header Summary only
                lines = raw_content.split('\n')
                header_comments = []
                for line in lines[:10]:
                    if line.strip().startswith(('#', '//', '/*', '*', '"""', "'''")):
                        header_comments.append(line)
                if header_comments:
                    formatted = "\n".join(header_comments) + "\n# ... [doc summary compressed] ..."
                else:
                    formatted = f"# Summary: {path.name} (Lines: {len(lines)})"
                tokens = len(formatted.split())

            # Only append if we can fit it or if it is very small
            if current_tokens + tokens <= target_budget or not result:
                result.append((path_str, formatted, tokens))
                current_tokens += tokens
            else:
                # Truncate and slide down
                lines = formatted.split('\n')
                formatted = "\n".join(lines[:5]) + "\n# ... [hard truncated] ..."
                tokens = len(formatted.split())
                if current_tokens + tokens <= target_budget:
                    result.append((path_str, formatted, tokens))
                    current_tokens += tokens

        return result

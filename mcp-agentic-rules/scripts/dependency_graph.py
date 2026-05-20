"""
MCP Codebase Dependency Graph & Ripple Impact Engine
===================================================
Constructs a macro codebase topological graph mapping dependencies, imports, 
and inheritance. Evaluates downstream ripple impacts of code changes.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple, Any

from .utils import find_python_files, find_project_root
from .treesitter_utils import parse_file, detect_language


class MacroCodebaseGraph:
    """
    Constructs and traverses the structural codebase graph.
    Maps file imports, class inheritances, and exported functions.
    """
    def __init__(self, root: Path = None):
        self.root = root or find_project_root() or Path.cwd()
        self.graph_path = self.root / '.mcp' / 'dependency_graph.json'
        
        # In-memory graph tables
        self.files: Dict[str, Dict[str, Any]] = {}  # file_path -> {imports, classes, functions}
        self.dependencies: Dict[str, List[str]] = {}  # file_path -> list of files it imports (outgoing)
        self.dependents: Dict[str, Set[str]] = {}  # file_path -> set of files importing it (incoming)
        self.inheritance: Dict[str, str] = {}  # class_name -> parent_class_name

    def build(self) -> dict:
        """Crawl the codebase and construct the macro graph."""
        # Find all python, js, ts, rust, go files
        exclude_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.mcp', 'build', 'dist'}
        all_files = []
        
        # Traverse recursively to match supported source files
        supported_exts = ('.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java', '.cpp', '.hpp', '.c', '.h')
        for p in self.root.rglob('*'):
            if p.is_file() and p.suffix.lower() in supported_exts:
                if not any(exclude in p.parts for exclude in exclude_dirs):
                    all_files.append(p)

        for path in all_files:
            relative_path = str(path.relative_to(self.root)).replace('\\', '/')
            
            try:
                parsed = parse_file(path)
                
                classes = [c.name for c in parsed.classes]
                functions = [f.name for f in parsed.functions]
                imports = parsed.imports
                
                self.files[relative_path] = {
                    "language": parsed.language,
                    "classes": classes,
                    "functions": functions,
                    "imports": imports
                }
                
                # Extract simple class inheritance from source using simple regex
                if parsed.language == 'python':
                    self._extract_python_inheritance(path, classes)
                
            except Exception:
                # Keep stub on parse errors
                self.files[relative_path] = {
                    "language": detect_language(path) or "unknown",
                    "classes": [],
                    "functions": [],
                    "imports": []
                }

        # Resolve import names to actual file paths in the workspace
        self._resolve_import_edges()
        
        # Serialize graph to file
        graph_data = {
            "files": self.files,
            "dependencies": self.dependencies,
            "dependents": {k: list(v) for k, v in self.dependents.items()},
            "inheritance": self.inheritance
        }
        
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.graph_path, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, indent=2)

        return graph_data

    def load(self) -> bool:
        """Load graph data from serialized JSON file."""
        if not self.graph_path.exists():
            return False
            
        try:
            with open(self.graph_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.files = data.get("files", {})
            self.dependencies = data.get("dependencies", {})
            
            # Reconstruct sets for dependents
            self.dependents = {}
            for k, v in data.get("dependents", {}).items():
                self.dependents[k] = set(v)
                
            self.inheritance = data.get("inheritance", {})
            return True
        except Exception:
            return False

    def _extract_python_inheritance(self, path: Path, classes: List[str]):
        """Helper to extract class inheritance for Python files."""
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            for cls_name in classes:
                pattern = re.compile(rf'class\s+{cls_name}\s*\(([^)]+)\)')
                match = pattern.search(content)
                if match:
                    parents = [p.strip() for p in match.group(1).split(',')]
                    # Just map the first parent for simplified dependency routing
                    if parents:
                        self.inheritance[cls_name] = parents[0]
        except Exception:
            pass

    def _resolve_import_edges(self):
        """Resolves raw import statements to actual relative file paths."""
        self.dependencies = {}
        self.dependents = {}
        
        # Initialize incoming arrays
        for rel_path in self.files.keys():
            self.dependencies[rel_path] = []
            self.dependents[rel_path] = set()

        for rel_path, meta in self.files.items():
            imports = meta.get("imports", [])
            for imp in imports:
                # 1. Clean import name (e.g. 'from scripts.utils import Console' -> 'scripts.utils')
                cleaned = imp.replace('from ', '').replace('import ', '').strip().split()[0]
                
                # Replace dots with slashes for resolution (e.g., Python imports)
                path_stem = cleaned.replace('.', '/')
                
                # Check for direct path match in our codebase
                resolved = False
                for target_path in self.files.keys():
                    target_stem = target_path.rsplit('.', 1)[0]
                    if target_stem == path_stem or target_stem.endswith('/' + path_stem):
                        if target_path != rel_path:
                            self.dependencies[rel_path].append(target_path)
                            self.dependents[target_path].add(rel_path)
                            resolved = True
                            break
                            
                # 2. Fallback relative/name match for curly-brace languages (e.g., matching filenames)
                if not resolved:
                    # Look for imported module strings (e.g., 'require("./utils")' or 'import { X } from "./utils"')
                    match = re.search(r'[\'"]([^\'"]+)[\'"]', imp)
                    if match:
                        imp_val = match.group(1).replace('../', '').replace('./', '')
                        for target_path in self.files.keys():
                            if imp_val in target_path and target_path != rel_path:
                                self.dependencies[rel_path].append(target_path)
                                self.dependents[target_path].add(rel_path)
                                break

    def get_ripple_impact(self, modified_file_path: str, changed_symbols: List[str] = None) -> List[str]:
        """
        Calculates the downstream files impacted by modifying a file or specific symbols.
        Uses BFS to traverse the dependents tree and regex references check.
        """
        # Normalize relative path separators
        norm_path = modified_file_path.replace('\\', '/')
        
        if norm_path not in self.files:
            return []

        impacted_files: Set[str] = set()
        queue: List[str] = [norm_path]
        visited: Set[str] = {norm_path}

        # Step 1: Perform BFS over import dependents tree (Direct + Transitive)
        while queue:
            current = queue.pop(0)
            incoming = self.dependents.get(current, set())
            
            for dep in incoming:
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)
                    
                    # If specific symbols were modified, verify if they are referenced
                    if changed_symbols:
                        if self._is_referencing_symbols(dep, changed_symbols):
                            impacted_files.add(dep)
                    else:
                        impacted_files.add(dep)

        # Step 2: Check for inheritance ripples
        # If any class in modified_file is a parent class, mark subclass files as impacted
        classes_in_file = self.files[norm_path].get("classes", [])
        for cls in classes_in_file:
            for subclass, parent in self.inheritance.items():
                if parent == cls:
                    # Find which file defines the subclass
                    for f_path, meta in self.files.items():
                        if subclass in meta.get("classes", []):
                            if f_path not in visited:
                                impacted_files.add(f_path)

        return sorted(list(impacted_files))

    def _is_referencing_symbols(self, file_path_str: str, symbols: List[str]) -> bool:
        """Helper to scan a file and verify if it references specific symbols."""
        abs_path = self.root / file_path_str
        if not abs_path.exists():
            return False
            
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            for sym in symbols:
                # Exact word match for symbol reference
                if re.search(rf'\b{re.escape(sym)}\b', content):
                    return True
        except Exception:
            pass
        return False

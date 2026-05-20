"""
Call Graph / Knowledge Graph
============================
Build and query a knowledge graph of code relationships.

Maps:
- Function A -> calls -> Function B
- Class A -> inherits -> Class B
- Module A -> imports -> Module B

Usage:
    python mcp.py graph "function_name"    # Find what calls/is called by
    python mcp.py graph --build            # Rebuild graph
    python mcp.py graph --stats            # Show graph statistics
"""

import ast
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

from .utils import (
    find_python_files,
    find_project_root,
    get_project_boundary,
    Console
)


@dataclass
class GraphNode:
    """A node in the call graph."""
    name: str
    node_type: str  # 'function', 'class', 'method', 'module'
    file: str
    line: int
    qualified_name: str  # e.g., "module.Class.method"


@dataclass
class GraphEdge:
    """An edge in the call graph."""
    source: str  # qualified name
    target: str  # qualified name
    edge_type: str  # 'calls', 'inherits', 'imports', 'instantiates'
    file: str
    line: int


@dataclass
class CallGraph:
    """The complete call graph for a codebase."""
    root: Path
    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    edges: List[GraphEdge] = field(default_factory=list)
    
    # Indexes for fast lookup
    callers: Dict[str, List[str]] = field(default_factory=dict)  # target -> [sources]
    callees: Dict[str, List[str]] = field(default_factory=dict)  # source -> [targets]
    
    def add_node(self, node: GraphNode):
        """Add a node to the graph."""
        self.nodes[node.qualified_name] = node
    
    def add_edge(self, edge: GraphEdge):
        """Add an edge and update indexes."""
        self.edges.append(edge)
        
        # Update caller index
        if edge.target not in self.callers:
            self.callers[edge.target] = []
        if edge.source not in self.callers[edge.target]:
            self.callers[edge.target].append(edge.source)
        
        # Update callee index
        if edge.source not in self.callees:
            self.callees[edge.source] = []
        if edge.target not in self.callees[edge.source]:
            self.callees[edge.source].append(edge.target)
    
    def get_callers(self, name: str) -> List[str]:
        """Get all functions that call the given name."""
        # Try exact match first
        if name in self.callers:
            return self.callers[name]
        
        # Try partial match
        matches = []
        for qualified_name, callers in self.callers.items():
            if qualified_name.endswith('.' + name) or qualified_name == name:
                matches.extend(callers)
        return list(set(matches))
    
    def get_callees(self, name: str) -> List[str]:
        """Get all functions called by the given name."""
        if name in self.callees:
            return self.callees[name]
        
        # Try partial match
        matches = []
        for qualified_name, callees in self.callees.items():
            if qualified_name.endswith('.' + name) or qualified_name == name:
                matches.extend(callees)
        return list(set(matches))
    
    def find_node(self, name: str) -> Optional[GraphNode]:
        """Find a node by name (exact or partial match)."""
        if name in self.nodes:
            return self.nodes[name]
        
        for qualified_name, node in self.nodes.items():
            if qualified_name.endswith('.' + name) or node.name == name:
                return node
        return None
    
    def search_nodes(self, query: str) -> List[GraphNode]:
        """Search for nodes matching query."""
        query_lower = query.lower()
        matches = []
        for qualified_name, node in self.nodes.items():
            if query_lower in qualified_name.lower() or query_lower in node.name.lower():
                matches.append(node)
        return matches
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'root': str(self.root),
            'nodes': {k: asdict(v) for k, v in self.nodes.items()},
            'edges': [asdict(e) for e in self.edges],
            'callers': self.callers,
            'callees': self.callees
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CallGraph':
        """Create from dictionary."""
        graph = cls(root=Path(data['root']))
        
        for k, v in data.get('nodes', {}).items():
            graph.nodes[k] = GraphNode(**v)
        
        for e in data.get('edges', []):
            graph.edges.append(GraphEdge(**e))
        
        graph.callers = data.get('callers', {})
        graph.callees = data.get('callees', {})
        
        return graph


class CallGraphBuilder(ast.NodeVisitor):
    """AST visitor to build call graph from Python files."""
    
    def __init__(self, graph: CallGraph, file_path: Path, module_name: str):
        self.graph = graph
        self.file_path = file_path
        self.module_name = module_name
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None
        self.imports: Dict[str, str] = {}  # alias -> module
    
    def get_current_scope(self) -> str:
        """Get the current qualified scope name."""
        parts = [self.module_name]
        if self.current_class:
            parts.append(self.current_class)
        if self.current_function:
            parts.append(self.current_function)
        return '.'.join(parts)
    
    def visit_Import(self, node: ast.Import):
        """Track imports."""
        for alias in node.names:
            name = alias.asname or alias.name
            self.imports[name] = alias.name
            
            # Add edge
            self.graph.add_edge(GraphEdge(
                source=self.module_name,
                target=alias.name,
                edge_type='imports',
                file=str(self.file_path),
                line=node.lineno
            ))
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Track from imports."""
        if node.module:
            for alias in node.names:
                name = alias.asname or alias.name
                self.imports[name] = f"{node.module}.{alias.name}"
                
                # Add edge
                self.graph.add_edge(GraphEdge(
                    source=self.module_name,
                    target=node.module,
                    edge_type='imports',
                    file=str(self.file_path),
                    line=node.lineno
                ))
        self.generic_visit(node)
    
    def visit_ClassDef(self, node: ast.ClassDef):
        """Process class definition."""
        qualified_name = f"{self.module_name}.{node.name}"
        
        # Add node
        self.graph.add_node(GraphNode(
            name=node.name,
            node_type='class',
            file=str(self.file_path),
            line=node.lineno,
            qualified_name=qualified_name
        ))
        
        # Add inheritance edges
        for base in node.bases:
            base_name = self._get_name(base)
            if base_name:
                self.graph.add_edge(GraphEdge(
                    source=qualified_name,
                    target=base_name,
                    edge_type='inherits',
                    file=str(self.file_path),
                    line=node.lineno
                ))
        
        # Process class body
        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class
    
    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Process function definition."""
        self._visit_function(node)
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Process async function definition."""
        self._visit_function(node)
    
    def _visit_function(self, node):
        """Process function/method definition."""
        if self.current_class:
            qualified_name = f"{self.module_name}.{self.current_class}.{node.name}"
            node_type = 'method'
        else:
            qualified_name = f"{self.module_name}.{node.name}"
            node_type = 'function'
        
        # Add node
        self.graph.add_node(GraphNode(
            name=node.name,
            node_type=node_type,
            file=str(self.file_path),
            line=node.lineno,
            qualified_name=qualified_name
        ))
        
        # Process function body for calls
        old_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_function
    
    def visit_Call(self, node: ast.Call):
        """Process function call."""
        if self.current_function:
            caller = self.get_current_scope()
            callee = self._get_call_name(node)
            
            if callee:
                self.graph.add_edge(GraphEdge(
                    source=caller,
                    target=callee,
                    edge_type='calls',
                    file=str(self.file_path),
                    line=node.lineno
                ))
        
        self.generic_visit(node)
    
    def _get_name(self, node: ast.expr) -> Optional[str]:
        """Get name from expression node."""
        if isinstance(node, ast.Name):
            # Check if it's an imported name
            return self.imports.get(node.id, node.id)
        elif isinstance(node, ast.Attribute):
            parts = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(self.imports.get(current.id, current.id))
            return '.'.join(reversed(parts))
        return None
    
    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        """Get the name of the called function."""
        return self._get_name(node.func)


def build_call_graph(root: Path, exclude_patterns: List[str] = None) -> CallGraph:
    """Build call graph for a codebase."""
    root = Path(root).resolve()
    graph = CallGraph(root=root)
    
    Console.info(f"Building call graph for {root}...")
    
    files = list(find_python_files(root, exclude_patterns))
    Console.info(f"Analyzing {len(files)} files...")
    
    for path in files:
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
            
            tree = ast.parse(source, filename=str(path))
            
            # Get module name from path
            try:
                relative = path.relative_to(root)
                module_name = str(relative.with_suffix('')).replace('/', '.').replace('\\', '.')
            except ValueError:
                module_name = path.stem
            
            # Add module node
            graph.add_node(GraphNode(
                name=path.name,
                node_type='module',
                file=str(path),
                line=1,
                qualified_name=module_name
            ))
            
            # Build graph from AST
            builder = CallGraphBuilder(graph, path, module_name)
            builder.visit(tree)
            
        except SyntaxError:
            Console.warn(f"Syntax error in {path}")
        except Exception as e:
            Console.warn(f"Error processing {path}: {e}")
    
    Console.ok(f"Built graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    
    return graph


def save_call_graph(graph: CallGraph, root: Path = None):
    """Save call graph to .mcp directory."""
    if root is None:
        root = graph.root
    
    mcp_dir = root / '.mcp'
    mcp_dir.mkdir(parents=True, exist_ok=True)
    
    graph_file = mcp_dir / 'call_graph.json'
    with open(graph_file, 'w', encoding='utf-8') as f:
        json.dump(graph.to_dict(), f, indent=2)
    
    Console.ok(f"Saved call graph to {graph_file}")


def load_call_graph(root: Path = None) -> Optional[CallGraph]:
    """Load call graph from .mcp directory."""
    if root is None:
        root = get_project_boundary() or find_project_root() or Path.cwd()
    
    graph_file = root / '.mcp' / 'call_graph.json'
    
    if not graph_file.exists():
        return None
    
    try:
        with open(graph_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return CallGraph.from_dict(data)
    except Exception as e:
        Console.warn(f"Could not load call graph: {e}")
        return None


def query_graph(graph: CallGraph, query: str) -> dict:
    """Query the call graph and return results."""
    results = {
        'query': query,
        'node': None,
        'callers': [],
        'callees': [],
        'related_files': set()
    }
    
    # Find the node
    node = graph.find_node(query)
    if node:
        results['node'] = asdict(node)
        results['related_files'].add(node.file)
    
    # Find callers (what calls this)
    callers = graph.get_callers(query)
    for caller_name in callers:
        caller_node = graph.nodes.get(caller_name)
        if caller_node:
            results['callers'].append({
                'name': caller_name,
                'file': caller_node.file,
                'line': caller_node.line
            })
            results['related_files'].add(caller_node.file)
    
    # Find callees (what this calls)
    callees = graph.get_callees(query)
    for callee_name in callees:
        callee_node = graph.nodes.get(callee_name)
        if callee_node:
            results['callees'].append({
                'name': callee_name,
                'file': callee_node.file,
                'line': callee_node.line
            })
            results['related_files'].add(callee_node.file)
    
    results['related_files'] = list(results['related_files'])
    return results


def format_query_result(result: dict) -> str:
    """Format query result as readable text."""
    lines = [
        f"# Graph Query: {result['query']}",
        ""
    ]
    
    if result['node']:
        node = result['node']
        lines.append(f"**Found:** `{node['qualified_name']}` ({node['node_type']})")
        lines.append(f"**File:** `{node['file']}:{node['line']}`")
        lines.append("")
    
    if result['callers']:
        lines.append(f"## Called By ({len(result['callers'])})")
        for caller in result['callers'][:10]:
            lines.append(f"- `{caller['name']}` ({caller['file']}:{caller['line']})")
        if len(result['callers']) > 10:
            lines.append(f"- ... and {len(result['callers']) - 10} more")
        lines.append("")
    
    if result['callees']:
        lines.append(f"## Calls ({len(result['callees'])})")
        for callee in result['callees'][:10]:
            lines.append(f"- `{callee['name']}` ({callee['file']}:{callee['line']})")
        if len(result['callees']) > 10:
            lines.append(f"- ... and {len(result['callees']) - 10} more")
        lines.append("")
    
    if result['related_files']:
        lines.append(f"## Related Files ({len(result['related_files'])})")
        for f in result['related_files'][:5]:
            lines.append(f"- `{f}`")
        lines.append("")
    
    if not result['callers'] and not result['callees'] and not result['node']:
        lines.append("No results found. Try rebuilding the graph: `mcp graph --build`")
    
    return '\n'.join(lines)


def main():
    """CLI entry point."""
    Console.header("Call Graph")
    
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    
    root = get_project_boundary() or find_project_root() or Path.cwd()
    
    # Build graph
    if '--build' in sys.argv or '--rebuild' in sys.argv:
        graph = build_call_graph(root)
        save_call_graph(graph, root)
        return 0
    
    # Show stats
    if '--stats' in sys.argv:
        graph = load_call_graph(root)
        if graph:
            print(f"Nodes: {len(graph.nodes)}")
            print(f"Edges: {len(graph.edges)}")
            
            # Count by type
            by_type = {}
            for node in graph.nodes.values():
                by_type[node.node_type] = by_type.get(node.node_type, 0) + 1
            print("\nBy type:")
            for t, count in sorted(by_type.items()):
                print(f"  {t}: {count}")
        else:
            Console.warn("No graph found. Run with --build first.")
        return 0
    
    # Query
    if args:
        query = args[0]
        
        graph = load_call_graph(root)
        if not graph:
            Console.info("Building graph first...")
            graph = build_call_graph(root)
            save_call_graph(graph, root)
        
        result = query_graph(graph, query)
        print(format_query_result(result))
        return 0
    
    # No args - show help
    Console.info("Usage:")
    Console.info("  mcp graph \"function_name\"  - Query what calls/is called by")
    Console.info("  mcp graph --build          - Build/rebuild the call graph")
    Console.info("  mcp graph --stats          - Show graph statistics")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

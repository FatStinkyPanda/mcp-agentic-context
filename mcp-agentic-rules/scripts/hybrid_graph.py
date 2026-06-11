"""
Hybrid Knowledge Graph
======================
Multi-dimensional vector correlation graph for advanced code understanding.

Combines 4 signal types:
- Semantic: Code meaning via embeddings
- Structural: Calls, imports, inherits
- Temporal: Files accessed together
- Co-Modification: Files changed together in git

Usage:
    python mcp.py hybrid-search "authentication"
    python mcp.py correlate
    python mcp.py learn-patterns
"""

import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any

from .utils import (
    find_python_files,
    find_project_root,
    get_project_boundary,
    run_git_command,
    Console
)


@dataclass
class HybridNode:
    """A node in the hybrid knowledge graph."""
    id: str  # Unique identifier (usually file path or qualified name)
    node_type: str  # 'file', 'function', 'class'
    path: str
    name: str
    
    # Multi-dimensional scores (0.0 to 1.0)
    semantic_embedding: List[float] = field(default_factory=list)
    structural_score: float = 0.0
    temporal_score: float = 0.0
    comod_score: float = 0.0
    
    # Metadata
    last_accessed: str = ""
    access_count: int = 0
    last_modified: str = ""
    
    def get_unified_score(
        self,
        semantic_weight: float = 0.30,
        structural_weight: float = 0.30,
        temporal_weight: float = 0.20,
        comod_weight: float = 0.20
    ) -> float:
        """Calculate unified score from all dimensions."""
        return (
            self.structural_score * structural_weight +
            self.temporal_score * temporal_weight +
            self.comod_score * comod_weight
        )


@dataclass 
class HybridEdge:
    """An edge in the hybrid graph with multiple relationship types."""
    source: str
    target: str
    
    # Edge weights by type
    structural_weight: float = 0.0  # calls, imports, inherits
    temporal_weight: float = 0.0    # accessed together
    comod_weight: float = 0.0       # modified together
    semantic_weight: float = 0.0    # similar embeddings
    
    # Metadata
    relationship_types: List[str] = field(default_factory=list)
    last_updated: str = ""
    
    def get_combined_weight(self) -> float:
        """Get combined edge weight."""
        return (
            self.structural_weight * 0.3 +
            self.temporal_weight * 0.2 +
            self.comod_weight * 0.3 +
            self.semantic_weight * 0.2
        )


@dataclass
class HybridGraph:
    """The complete hybrid knowledge graph."""
    root: Path
    nodes: Dict[str, HybridNode] = field(default_factory=dict)
    edges: Dict[str, HybridEdge] = field(default_factory=dict)  # "source|target" -> edge
    
    # Indexes for fast lookup
    neighbors: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    
    # Correlation data
    access_history: List[Tuple[str, str]] = field(default_factory=list)  # (node_id, timestamp)
    comod_matrix: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    
    def add_node(self, node: HybridNode):
        """Add or update a node."""
        self.nodes[node.id] = node
    
    def add_edge(self, source: str, target: str, relationship_type: str, weight: float = 1.0):
        """Add or update an edge."""
        edge_id = f"{source}|{target}"
        
        if edge_id not in self.edges:
            self.edges[edge_id] = HybridEdge(source=source, target=target)
        
        edge = self.edges[edge_id]
        edge.last_updated = datetime.utcnow().isoformat() + 'Z'
        
        if relationship_type not in edge.relationship_types:
            edge.relationship_types.append(relationship_type)
        
        # Update appropriate weight
        if relationship_type in ('calls', 'imports', 'inherits'):
            edge.structural_weight = max(edge.structural_weight, weight)
        elif relationship_type == 'accessed_together':
            edge.temporal_weight = min(1.0, edge.temporal_weight + weight * 0.1)
        elif relationship_type == 'modified_together':
            edge.comod_weight = min(1.0, edge.comod_weight + weight * 0.1)
        elif relationship_type == 'similar':
            edge.semantic_weight = max(edge.semantic_weight, weight)
        
        # Update neighbor index
        self.neighbors[source].add(target)
        self.neighbors[target].add(source)
    
    def record_access(self, node_id: str):
        """Record file access for temporal correlation."""
        timestamp = datetime.utcnow().isoformat() + 'Z'
        self.access_history.append((node_id, timestamp))
        
        # Keep only recent history (last 1000 accesses)
        if len(self.access_history) > 1000:
            self.access_history = self.access_history[-1000:]
        
        # Update node access stats
        if node_id in self.nodes:
            self.nodes[node_id].last_accessed = timestamp
            self.nodes[node_id].access_count += 1
        
        # Create temporal edges for files accessed within 5 minutes
        cutoff = (datetime.utcnow() - timedelta(minutes=5)).isoformat() + 'Z'
        recent = [nid for nid, ts in self.access_history if ts > cutoff and nid != node_id]
        
        for other_id in recent[-5:]:  # Last 5 recent
            self.add_edge(node_id, other_id, 'accessed_together', weight=0.5)
    
    def record_comodification(self, files: List[str]):
        """Record files modified together in a commit."""
        for i, f1 in enumerate(files):
            for f2 in files[i+1:]:
                self.comod_matrix[f1][f2] += 1
                self.comod_matrix[f2][f1] += 1
                
                # Create/strengthen edge
                count = self.comod_matrix[f1][f2]
                weight = min(1.0, count * 0.2)  # Cap at 5 co-modifications
                self.add_edge(f1, f2, 'modified_together', weight=weight)
    
    def get_related_nodes(self, query_id: str, limit: int = 10) -> List[Tuple[str, float]]:
        """Get nodes related to query, ranked by hybrid score."""
        if query_id not in self.nodes:
            return []
        
        scores = {}
        
        # Get direct neighbors
        for neighbor_id in self.neighbors.get(query_id, set()):
            edge_id = f"{query_id}|{neighbor_id}"
            if edge_id not in self.edges:
                edge_id = f"{neighbor_id}|{query_id}"
            
            if edge_id in self.edges:
                edge = self.edges[edge_id]
                scores[neighbor_id] = edge.get_combined_weight()
        
        # Sort by score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:limit]
    
    def search(self, query: str, limit: int = 10) -> List[Tuple[HybridNode, float]]:
        """Search nodes using all dimensions."""
        results = []
        query_lower = query.lower()
        
        for node_id, node in self.nodes.items():
            score = 0.0
            
            # Name match boost
            if query_lower in node.name.lower():
                score += 0.5
            if query_lower in node.path.lower():
                score += 0.3
            
            # Add node's inherent scores
            score += node.structural_score * 0.2
            score += node.temporal_score * 0.1
            score += node.comod_score * 0.1
            
            if score > 0:
                results.append((node, score))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            'root': str(self.root),
            'nodes': {k: asdict(v) for k, v in self.nodes.items()},
            'edges': {k: asdict(v) for k, v in self.edges.items()},
            'neighbors': {k: list(v) for k, v in self.neighbors.items()},
            'comod_matrix': {k: dict(v) for k, v in self.comod_matrix.items()},
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'HybridGraph':
        """Deserialize from dictionary."""
        graph = cls(root=Path(data['root']))
        
        for k, v in data.get('nodes', {}).items():
            graph.nodes[k] = HybridNode(**v)
        
        for k, v in data.get('edges', {}).items():
            graph.edges[k] = HybridEdge(**v)
        
        for k, v in data.get('neighbors', {}).items():
            graph.neighbors[k] = set(v)
        
        for k, v in data.get('comod_matrix', {}).items():
            graph.comod_matrix[k] = defaultdict(int, v)
        
        return graph


def get_hybrid_graph_path(root: Path) -> Path:
    """Get path to hybrid graph file."""
    return root / '.mcp' / 'hybrid_graph.json'


def load_hybrid_graph(root: Path = None) -> Optional[HybridGraph]:
    """Load hybrid graph from disk."""
    if root is None:
        root = get_project_boundary() or find_project_root() or Path.cwd()
    
    graph_path = get_hybrid_graph_path(root)
    
    if graph_path.exists():
        try:
            with open(graph_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return HybridGraph.from_dict(data)
        except Exception as e:
            Console.warn(f"Could not load hybrid graph: {e}")
    
    return None


def save_hybrid_graph(graph: HybridGraph):
    """Save hybrid graph to disk."""
    graph_path = get_hybrid_graph_path(graph.root)
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(graph_path, 'w', encoding='utf-8') as f:
        json.dump(graph.to_dict(), f, indent=2)
    
    Console.ok(f"Saved hybrid graph to {graph_path}")


def build_hybrid_graph(root: Path = None) -> HybridGraph:
    """Build hybrid graph combining all dimensions."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    
    Console.info(f"Building hybrid graph for {root}...")
    
    graph = HybridGraph(root=root)
    
    # 1. Add file nodes
    files = list(find_python_files(root))
    Console.info(f"Found {len(files)} files")
    
    for path in files:
        node_id = str(path)
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = path
        
        graph.add_node(HybridNode(
            id=node_id,
            node_type='file',
            path=str(path),
            name=path.name
        ))
    
    # 2. Add structural edges from call graph
    try:
        from .call_graph import load_call_graph
        call_graph = load_call_graph(root)
        
        if call_graph:
            for edge in call_graph.edges:
                # Map to file-level edges
                source_node = call_graph.nodes.get(edge.source)
                target_node = call_graph.nodes.get(edge.target)
                
                if source_node and target_node:
                    source_file = source_node.file
                    target_file = target_node.file
                    
                    if source_file != target_file:
                        graph.add_edge(source_file, target_file, edge.edge_type, weight=1.0)
            
            Console.info(f"Added {len(call_graph.edges)} structural edges")
    except Exception as e:
        Console.warn(f"Could not load call graph: {e}")
    
    # 3. Add co-modification from git history
    try:
        # Get commits with file lists
        output = run_git_command(
            ['log', '--name-only', '--format=%H', '-n', '100'],
            cwd=root
        )
        
        if output:
            commits = output.strip().split('\n\n')
            comod_count = 0
            
            for commit_block in commits:
                lines = commit_block.strip().split('\n')
                if len(lines) > 1:
                    files_in_commit = [str(root / f) for f in lines[1:] if f.endswith('.py')]
                    if len(files_in_commit) > 1:
                        graph.record_comodification(files_in_commit)
                        comod_count += 1
            
            Console.info(f"Processed {comod_count} commits for co-modification")
    except Exception as e:
        Console.warn(f"Could not analyze git history: {e}")
    
    # 4. Calculate node scores
    for node_id, node in graph.nodes.items():
        # Structural score: based on number of connections
        neighbor_count = len(graph.neighbors.get(node_id, set()))
        node.structural_score = min(1.0, neighbor_count * 0.1)
        
        # Comod score: based on co-modification count
        comod_total = sum(graph.comod_matrix.get(node_id, {}).values())
        node.comod_score = min(1.0, comod_total * 0.05)
    
    Console.ok(f"Built graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    
    return graph


def hybrid_search(query: str, root: Path = None, limit: int = 10) -> List[Tuple[str, float, List[str]]]:
    """
    Search using hybrid graph.
    
    Returns: List of (file_path, score, relationship_types)
    """
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    
    graph = load_hybrid_graph(root)
    if not graph:
        Console.info("Building hybrid graph first...")
        graph = build_hybrid_graph(root)
        save_hybrid_graph(graph)
    
    # Search
    results = graph.search(query, limit=limit)
    
    # Format results
    formatted = []
    for node, score in results:
        # Get relationship types from edges
        rel_types = set()
        for edge_id, edge in graph.edges.items():
            if node.id in edge_id:
                rel_types.update(edge.relationship_types)
        
        formatted.append((node.path, score, list(rel_types)))
    
    return formatted


def format_search_results(results: List[Tuple[str, float, List[str]]]) -> str:
    """Format search results as markdown."""
    lines = [
        "# Hybrid Search Results",
        "",
        f"**Found:** {len(results)} files",
        "",
    ]
    
    for path, score, rel_types in results:
        rel_str = ", ".join(rel_types[:3]) if rel_types else "name match"
        lines.append(f"- `{Path(path).name}` (score: {score:.2f})")
        lines.append(f"  - Path: `{path}`")
        lines.append(f"  - Relationships: {rel_str}")
    
    return '\n'.join(lines)


def main():
    """CLI entry point."""
    Console.header("Hybrid Knowledge Graph")
    
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    root = get_project_boundary() or find_project_root() or Path.cwd()
    
    # Build/rebuild
    if '--build' in sys.argv or '--rebuild' in sys.argv:
        graph = build_hybrid_graph(root)
        save_hybrid_graph(graph)
        return 0
    
    # Show stats
    if '--stats' in sys.argv:
        graph = load_hybrid_graph(root)
        if graph:
            print(f"Nodes: {len(graph.nodes)}")
            print(f"Edges: {len(graph.edges)}")
            
            # Edge type breakdown
            type_counts = defaultdict(int)
            for edge in graph.edges.values():
                for rt in edge.relationship_types:
                    type_counts[rt] += 1
            
            print("\nEdge types:")
            for rt, count in sorted(type_counts.items()):
                print(f"  {rt}: {count}")
        else:
            Console.warn("No graph found. Run with --build first.")
        return 0
    
    # Correlate (show co-modification patterns)
    if '--correlate' in sys.argv or 'correlate' in args:
        graph = load_hybrid_graph(root)
        if graph:
            print("# Top Co-Modified Files\n")
            
            # Flatten and sort comod matrix
            pairs = []
            seen = set()
            for f1, others in graph.comod_matrix.items():
                for f2, count in others.items():
                    key = tuple(sorted([f1, f2]))
                    if key not in seen:
                        seen.add(key)
                        pairs.append((f1, f2, count))
            
            pairs.sort(key=lambda x: x[2], reverse=True)
            
            for f1, f2, count in pairs[:15]:
                print(f"- {Path(f1).name} <-> {Path(f2).name} ({count} times)")
        return 0
    
    # Search
    if args:
        query = ' '.join(args)
        results = hybrid_search(query, root)
        print(format_search_results(results))
        return 0
    
    # Help
    Console.info("Usage:")
    Console.info("  mcp hybrid-search \"query\"  - Multi-dimensional search")
    Console.info("  mcp hybrid-search --build  - Build/rebuild graph")
    Console.info("  mcp hybrid-search --stats  - Show graph statistics")
    Console.info("  mcp correlate              - Show file correlations")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

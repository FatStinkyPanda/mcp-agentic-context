"""
Vector Store
=============
Local FAISS-based vector database for semantic code search.

Usage:
    from scripts.vector_store import VectorStore

    store = VectorStore(path)
    store.index_codebase(root)
    results = store.search("authentication handler", k=10)
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
import hashlib

from .utils import Console, find_source_files, find_project_root, get_mcp_dir
from .embeddings import embed_text, embed_texts, cosine_similarity, embedding_dimension


# Upper bound on files scanned in a single full index, to keep a pathologically
# large repo from exhausting memory. Override with MCP_MAX_FILES=0 (unlimited).
def _max_files() -> Optional[int]:
    raw = os.environ.get('MCP_MAX_FILES')
    if raw is None:
        return 20000
    try:
        val = int(raw)
    except ValueError:
        return 20000
    return None if val <= 0 else val


# Try to import FAISS
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

# Try numpy
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


@dataclass
class CodeChunk:
    """A chunk of code with metadata."""
    id: str
    path: str
    content: str
    chunk_type: str  # 'function', 'class', 'file', 'block'
    line_start: int
    line_end: int
    language: str = ""
    name: str = ""


@dataclass
class SearchResult:
    """A search result."""
    chunk: CodeChunk
    score: float
    rank: int


class VectorStore:
    """Local vector store for semantic code search."""

    def __init__(self, index_path: Optional[Path] = None):
        if index_path is None:
            self.index_path = get_mcp_dir() / "vector_index"
        else:
            self.index_path = Path(index_path)

        self.chunks: Dict[str, CodeChunk] = {}
        self.embeddings: Dict[str, List[float]] = {}
        self._faiss_index = None
        self._id_to_idx: Dict[str, int] = {}
        self._idx_to_id: Dict[int, str] = {}

    def index_codebase(self, root: Path, exclude_patterns: List[str] = None, changed_files: List[Path] = None) -> int:
        """Index all code files in directory, or update only changed_files."""
        Console.info(f"Indexing codebase in {root}...")

        is_incremental = False
        if changed_files is not None:
            if self.load():
                is_incremental = True
                Console.info(f"Loaded existing vector index. Performing incremental update for {len(changed_files)} files...")
            else:
                Console.warn("No existing vector index found; performing full index.")
                changed_files = None

        if is_incremental and changed_files is not None:
            # Convert paths to relative strings for consistency in the index
            changed_rel_paths = {str(Path(f).relative_to(root)) if Path(f).is_absolute() else str(f) for f in changed_files}

            # Evict old chunks belonging to changed files
            old_ids = [cid for cid, chunk in self.chunks.items() if chunk.path in changed_rel_paths]
            for cid in old_ids:
                if cid in self.chunks:
                    del self.chunks[cid]
                if cid in self.embeddings:
                    del self.embeddings[cid]

            # Scan only changed files
            chunks = []
            for path in changed_files:
                if path.exists():
                    file_chunks = self._extract_chunks(path)
                    for chunk in file_chunks:
                        try:
                            rel_path = Path(chunk.path).relative_to(root)
                            chunk.path = str(rel_path)
                        except ValueError:
                            pass
                        chunks.append(chunk)

            Console.info(f"Extracted {len(chunks)} new code chunks")

            if chunks:
                # Generate embeddings
                Console.info("Generating embeddings for new chunks...")
                texts = [c.content[:1000] for c in chunks]
                embeddings = embed_texts(texts)

                # Store new chunks and embeddings
                for chunk, emb in zip(chunks, embeddings):
                    self.chunks[chunk.id] = chunk
                    self.embeddings[chunk.id] = emb

            # Rebuild FAISS index if available
            if FAISS_AVAILABLE and NUMPY_AVAILABLE:
                self._build_faiss_index()

            # Save to disk
            self.save()
            Console.ok(f"Incremental indexing complete. Total chunks in index: {len(self.chunks)}")
            return len(self.chunks)

        else:
            cap = _max_files()
            extra_excludes = set(exclude_patterns) if exclude_patterns else None
            files = list(find_source_files(root, exclude_dirs=extra_excludes, max_files=cap))
            if cap is not None and len(files) >= cap:
                Console.warn(
                    f"Reached the {cap}-file scan cap; indexing the first {cap} files. "
                    "Set MCP_MAX_FILES=0 to index everything."
                )
            Console.info(f"Found {len(files)} files")

            chunks = []
            for path in files:
                file_chunks = self._extract_chunks(path)
                for chunk in file_chunks:
                    try:
                        rel_path = Path(chunk.path).relative_to(root)
                        chunk.path = str(rel_path)
                    except ValueError:
                        pass
                    chunks.append(chunk)

            Console.info(f"Extracted {len(chunks)} code chunks")

            if not chunks:
                return 0

            # Generate embeddings
            Console.info("Generating embeddings...")
            texts = [c.content[:1000] for c in chunks]
            embeddings = embed_texts(texts)

            # Store chunks and embeddings
            self.chunks = {}
            self.embeddings = {}
            for chunk, emb in zip(chunks, embeddings):
                self.chunks[chunk.id] = chunk
                self.embeddings[chunk.id] = emb

            # Build FAISS index if available
            if FAISS_AVAILABLE and NUMPY_AVAILABLE:
                self._build_faiss_index()

            # Save to disk
            self.save()

            Console.ok(f"Indexed {len(chunks)} chunks")
            return len(chunks)

    def _extract_chunks(self, path: Path) -> List[CodeChunk]:
        """Extract code chunks from file."""
        chunks = []

        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception:
            return chunks

        # Detect language
        ext = path.suffix.lower()
        lang_map = {
            '.py': 'python', '.pyi': 'python',
            '.js': 'javascript', '.jsx': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
            '.ts': 'typescript', '.tsx': 'typescript', '.mts': 'typescript', '.cts': 'typescript',
            '.vue': 'vue', '.svelte': 'svelte', '.astro': 'astro',
            '.go': 'go', '.rs': 'rust', '.java': 'java', '.kt': 'kotlin',
            '.c': 'c', '.h': 'c', '.cc': 'cpp', '.cpp': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp',
            '.cs': 'c_sharp', '.rb': 'ruby', '.php': 'php', '.swift': 'swift',
            '.sh': 'bash', '.bash': 'bash', '.sql': 'sql',
        }
        language = lang_map.get(ext, 'unknown')

        # Create file-level chunk
        file_id = hashlib.md5(str(path).encode()).hexdigest()[:12]
        chunks.append(CodeChunk(
            id=f"{file_id}_file",
            path=str(path),
            content=content[:2000],  # First 2000 chars
            chunk_type='file',
            line_start=1,
            line_end=content.count('\n') + 1,
            language=language,
            name=path.name
        ))

        # Try to extract functions/classes using treesitter
        try:
            from .treesitter_utils import parse_file
            parsed = parse_file(path)

            lines = content.split('\n')

            for func in parsed.functions:
                func_content = '\n'.join(lines[func.line_start-1:func.line_end])
                chunks.append(CodeChunk(
                    id=f"{file_id}_func_{func.name}",
                    path=str(path),
                    content=func_content[:1000],
                    chunk_type='function',
                    line_start=func.line_start,
                    line_end=func.line_end,
                    language=language,
                    name=func.name
                ))

            for cls in parsed.classes:
                cls_content = '\n'.join(lines[cls.line_start-1:cls.line_end])
                chunks.append(CodeChunk(
                    id=f"{file_id}_class_{cls.name}",
                    path=str(path),
                    content=cls_content[:1000],
                    chunk_type='class',
                    line_start=cls.line_start,
                    line_end=cls.line_end,
                    language=language,
                    name=cls.name
                ))

        except Exception:
            pass  # Fall back to file-level only

        return chunks

    def _build_faiss_index(self):
        """Build FAISS index from embeddings."""
        if not self.embeddings:
            return

        dim = len(next(iter(self.embeddings.values())))

        # Create index
        self._faiss_index = faiss.IndexFlatIP(dim)  # Inner product = cosine for normalized

        # Add vectors
        ids = list(self.embeddings.keys())
        vectors = np.array([self.embeddings[id] for id in ids], dtype='float32')

        # Normalize for cosine similarity
        faiss.normalize_L2(vectors)

        self._faiss_index.add(vectors)

        # Build ID mappings
        for idx, id in enumerate(ids):
            self._id_to_idx[id] = idx
            self._idx_to_id[idx] = id

    def search(self, query: str, k: int = 10) -> List[SearchResult]:
        """Search for code matching query."""
        if not self.embeddings:
            return []

        # Generate query embedding
        query_emb = embed_text(query)
        if query_emb is None:
            return []

        # Use FAISS if available
        if self._faiss_index is not None and NUMPY_AVAILABLE:
            return self._faiss_search(query_emb, k)

        # Fallback to brute force
        return self._brute_force_search(query_emb, k)

    def _faiss_search(self, query_emb: List[float], k: int) -> List[SearchResult]:
        """Search using FAISS."""
        query_vec = np.array([query_emb], dtype='float32')
        faiss.normalize_L2(query_vec)

        k = min(k, len(self.embeddings))
        distances, indices = self._faiss_index.search(query_vec, k)

        results = []
        for rank, (dist, idx) in enumerate(zip(distances[0], indices[0])):
            if idx < 0:
                continue
            chunk_id = self._idx_to_id.get(int(idx))
            if chunk_id and chunk_id in self.chunks:
                results.append(SearchResult(
                    chunk=self.chunks[chunk_id],
                    score=float(dist),
                    rank=rank + 1
                ))

        return results

    def _brute_force_search(self, query_emb: List[float], k: int) -> List[SearchResult]:
        """Brute force cosine similarity search."""
        scores = []

        for chunk_id, emb in self.embeddings.items():
            score = cosine_similarity(query_emb, emb)
            scores.append((chunk_id, score))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for rank, (chunk_id, score) in enumerate(scores[:k]):
            if chunk_id in self.chunks:
                results.append(SearchResult(
                    chunk=self.chunks[chunk_id],
                    score=score,
                    rank=rank + 1
                ))

        return results

    def save(self):
        """Save index to disk."""
        self.index_path.mkdir(parents=True, exist_ok=True)

        # Save chunks
        chunks_file = self.index_path / "chunks.json"
        with open(chunks_file, 'w', encoding='utf-8') as f:
            json.dump({k: asdict(v) for k, v in self.chunks.items()}, f)

        # Save embeddings
        emb_file = self.index_path / "embeddings.json"
        with open(emb_file, 'w', encoding='utf-8') as f:
            json.dump(self.embeddings, f)

        Console.ok(f"Index saved to {self.index_path}")

    def load(self) -> bool:
        """Load index from disk."""
        chunks_file = self.index_path / "chunks.json"
        emb_file = self.index_path / "embeddings.json"

        if not chunks_file.exists() or not emb_file.exists():
            return False

        try:
            with open(chunks_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.chunks = {k: CodeChunk(**v) for k, v in data.items()}

            with open(emb_file, 'r', encoding='utf-8') as f:
                self.embeddings = json.load(f)

            if FAISS_AVAILABLE and NUMPY_AVAILABLE:
                self._build_faiss_index()

            Console.ok(f"Loaded {len(self.chunks)} chunks from index")
            return True

        except Exception as e:
            Console.warn(f"Could not load index: {e}")
            return False

    def update(self, changed_files: List[Path]):
        """Update index for changed files."""
        for path in changed_files:
            # Remove old chunks for this file
            to_remove = [k for k, v in self.chunks.items() if v.path == str(path)]
            for k in to_remove:
                del self.chunks[k]
                if k in self.embeddings:
                    del self.embeddings[k]

            # Re-index file
            if path.exists():
                new_chunks = self._extract_chunks(path)
                if new_chunks:
                    texts = [c.content[:1000] for c in new_chunks]
                    embeddings = embed_texts(texts)

                    for chunk, emb in zip(new_chunks, embeddings):
                        self.chunks[chunk.id] = chunk
                        self.embeddings[chunk.id] = emb

        # Rebuild FAISS index
        if FAISS_AVAILABLE and NUMPY_AVAILABLE:
            self._build_faiss_index()

        self.save()


def main():
    """CLI entry point."""
    Console.header("Vector Store")

    if FAISS_AVAILABLE:
        Console.ok("FAISS available")
    else:
        Console.warn("FAISS not available, using brute force search")

    args = [a for a in sys.argv[1:] if not a.startswith('-')]

    # When dispatched through mcp.py the verb (index/search) is stripped from
    # argv and exposed via MCP_COMMAND instead; direct script invocation still
    # passes the verb as the first positional argument.
    known_commands = ('index', 'search')
    invoked = os.environ.get('MCP_COMMAND', '')
    if args and args[0] in known_commands:
        command = args[0]
        args = args[1:]
    elif invoked in known_commands:
        command = invoked
    else:
        Console.info("Usage: python vector_store.py <command> [args]")
        Console.info("Commands:")
        Console.info("  index <path>     Index codebase")
        Console.info("  search <query>   Search index")
        return 1

    store = VectorStore()

    if command == 'index':
        root = find_project_root() or Path.cwd()
        path = Path(args[0]) if args else root
        store.index_codebase(path)

    elif command == 'search':
        query = ' '.join(args)
        if not query:
            Console.fail("No query provided")
            return 1

        # Load existing index
        if not store.load():
            Console.fail("No index found. Run 'index' first.")
            return 1

        Console.info(f"Searching: {query}")
        results = store.search(query, k=10)

        for r in results:
            print(f"\n[{r.rank}] {r.chunk.path}:{r.chunk.line_start} (score: {r.score:.3f})")
            print(f"    {r.chunk.chunk_type}: {r.chunk.name}")
            print(f"    {r.chunk.content[:100]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())

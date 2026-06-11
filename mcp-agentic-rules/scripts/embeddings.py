"""
Embeddings Generation
=====================
Generate vector embeddings for code semantic search.
Uses sentence-transformers or falls back to TF-IDF.

Usage:
    from scripts.embeddings import embed_text, embed_code
"""

import sys
import re
import math
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .utils import Console


# sentence-transformers (which pulls torch) costs many seconds just to
# IMPORT, so it is resolved lazily inside get_model(). Commands that never
# need the model - and clients whose query is answered by the warm serve
# daemon - must not pay that import tax.
TRANSFORMERS_AVAILABLE: Optional[bool] = None  # unknown until first use

# Try to import numpy
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


# Model cache
_model = None
_model_name = "all-MiniLM-L6-v2"  # 22MB, good quality/speed balance


def _transformers_available() -> bool:
    """Resolve (and cache) whether sentence-transformers is importable."""
    global TRANSFORMERS_AVAILABLE
    if TRANSFORMERS_AVAILABLE is None:
        try:
            import sentence_transformers  # noqa: F401
            TRANSFORMERS_AVAILABLE = True
        except ImportError:
            TRANSFORMERS_AVAILABLE = False
    return TRANSFORMERS_AVAILABLE


def get_model():
    """Get or load embedding model (lazy heavy import)."""
    global _model

    if _model is not None:
        return _model

    if not _transformers_available():
        return None

    try:
        from sentence_transformers import SentenceTransformer
        # Try to load from local cache first
        _model = SentenceTransformer(_model_name)
        return _model
    except Exception as e:
        Console.warn(f"Could not load embedding model: {e}")
        return None


def embed_text(text: str) -> Optional[List[float]]:
    """Generate embedding for text."""
    model = get_model()

    if model is not None:
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    # Fallback to simple TF-IDF-like embedding
    return _fallback_embed(text)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for multiple texts."""
    model = get_model()

    if model is not None:
        embeddings = model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    # Fallback
    return [_fallback_embed(t) for t in texts]


def embed_code(code: str, language: str = "python") -> Optional[List[float]]:
    """Generate embedding for code with language-aware preprocessing."""
    # Preprocess code for better embeddings
    processed = _preprocess_code(code, language)
    return embed_text(processed)


def _preprocess_code(code: str, language: str) -> str:
    """Preprocess code for embedding."""
    # Remove comments based on language
    if language in ('python', 'ruby'):
        code = re.sub(r'#.*$', '', code, flags=re.MULTILINE)
    elif language in ('javascript', 'typescript', 'java', 'c', 'cpp', 'go', 'rust'):
        code = re.sub(r'//.*$', '', code, flags=re.MULTILINE)
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)

    # Normalize whitespace
    code = ' '.join(code.split())

    # Split camelCase and snake_case for better semantic matching
    code = re.sub(r'([a-z])([A-Z])', r'\1 \2', code)
    code = code.replace('_', ' ')

    return code.lower()


def _stable_hash(token: str) -> int:
    """
    Deterministic 32-bit hash, stable across processes and Python runs.

    The previous implementation used the builtin hash(), which is salted per
    process via PYTHONHASHSEED. That made index-time and query-time embeddings
    (run in separate processes) land in different feature buckets, so fallback
    semantic search returned effectively random results. crc32 is deterministic.
    """
    return zlib.crc32(token.encode('utf-8')) & 0xFFFFFFFF


_CAMEL_SPLIT = re.compile(r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+')


def _tokenize(text: str) -> List[str]:
    """
    Tokenize text/code into semantic tokens.

    Splits on non-alphanumerics (so snake_case becomes separate tokens) and
    additionally splits camelCase/PascalCase identifiers into subtokens, so a
    natural-language query like "user name" can match getUserName in code.
    """
    tokens: List[str] = []
    for word in re.findall(r'[A-Za-z0-9]+', text):
        low = word.lower()
        tokens.append(low)
        parts = _CAMEL_SPLIT.findall(word)
        if len(parts) > 1:
            for part in parts:
                pl = part.lower()
                if pl and pl != low:
                    tokens.append(pl)
    return tokens


def _fallback_embed(text: str, dim: int = 384) -> List[float]:
    """
    Deterministic fallback embedding using the signed feature-hashing trick.

    Used whenever sentence-transformers is unavailable. Properties:
    - Deterministic across processes (stable hash), so indexed and queried
      vectors share the same space - this is what makes search actually work.
    - Identifier-aware tokenization (camelCase/snake_case split).
    - Sublinear term weighting and signed buckets to reduce collision bias.
    """
    counts: Dict[str, int] = {}
    for tok in _tokenize(text):
        counts[tok] = counts.get(tok, 0) + 1

    if not counts:
        return [0.0] * dim

    embedding = [0.0] * dim
    for tok, cnt in counts.items():
        h = _stable_hash(tok)
        idx = h % dim
        sign = 1.0 if (h >> 31) & 1 else -1.0
        weight = 1.0 + math.log(cnt)  # sublinear term frequency
        embedding[idx] += sign * weight

    # L2 normalize so cosine similarity is well-behaved.
    norm = math.sqrt(sum(x * x for x in embedding))
    if norm > 0:
        embedding = [x / norm for x in embedding]

    return embedding


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def embedding_dimension() -> int:
    """Get embedding dimension."""
    model = get_model()
    if model is not None:
        return model.get_sentence_embedding_dimension()
    return 384  # Fallback dimension


def is_transformers_available() -> bool:
    """Check if sentence-transformers is available (resolves lazily)."""
    return _transformers_available()


@dataclass
class EmbeddingResult:
    """Result of embedding generation."""
    text: str
    embedding: List[float]
    method: str  # 'transformer' or 'fallback'


def embed_with_info(text: str) -> EmbeddingResult:
    """Generate embedding with metadata."""
    model = get_model()

    if model is not None:
        embedding = model.encode(text, convert_to_numpy=True).tolist()
        return EmbeddingResult(text=text, embedding=embedding, method='transformer')

    embedding = _fallback_embed(text)
    return EmbeddingResult(text=text, embedding=embedding, method='fallback')


def main():
    """CLI entry point."""
    Console.header("Embedding Generation")

    if _transformers_available():
        Console.ok("sentence-transformers available")
        model = get_model()
        if model:
            Console.ok(f"Model: {_model_name}")
            Console.ok(f"Dimension: {embedding_dimension()}")
    else:
        Console.warn("sentence-transformers not available, using fallback")
        Console.info(f"Fallback dimension: 384")

    # Test embedding
    args = [a for a in sys.argv[1:] if not a.startswith('-')]

    if args:
        text = ' '.join(args)
        Console.info(f"Embedding: {text[:50]}...")

        result = embed_with_info(text)
        Console.ok(f"Method: {result.method}")
        Console.ok(f"Dimension: {len(result.embedding)}")
        Console.ok(f"Sample values: {result.embedding[:5]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

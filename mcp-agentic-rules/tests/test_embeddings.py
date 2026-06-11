"""
Tests for the deterministic fallback embedding path.
=====================================================
These guard the fix for the per-process hash-salting bug that silently
broke semantic search whenever sentence-transformers was unavailable.
"""

import math
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _cos(a, b):
    from scripts.embeddings import cosine_similarity
    return cosine_similarity(a, b)


class TestFallbackEmbeddings:
    """Tests for _fallback_embed."""

    def test_dimension_and_normalized(self):
        from scripts.embeddings import _fallback_embed
        vec = _fallback_embed("authentication handler for the login route")
        if len(vec) != 384:
            raise AssertionError(f"Expected dim 384, got {len(vec)}")
        norm = math.sqrt(sum(x * x for x in vec))
        if abs(norm - 1.0) > 1e-6:
            raise AssertionError(f"Embedding should be L2-normalized, norm={norm}")

    def test_deterministic_same_process(self):
        from scripts.embeddings import _fallback_embed
        a = _fallback_embed("getUserProfile from the database")
        b = _fallback_embed("getUserProfile from the database")
        if a != b:
            raise AssertionError("Embeddings must be deterministic within a process")

    def test_empty_text(self):
        from scripts.embeddings import _fallback_embed
        vec = _fallback_embed("!!! ;;; ...")
        if any(v != 0.0 for v in vec):
            raise AssertionError("Token-free text should embed to the zero vector")

    def test_camelcase_splitting_improves_match(self):
        from scripts.embeddings import _fallback_embed
        query = _fallback_embed("user name")
        relevant = _fallback_embed("function getUserName() { return this.userName; }")
        irrelevant = _fallback_embed("class DatabaseMigrationRunner { run() {} }")
        if _cos(query, relevant) <= _cos(query, irrelevant):
            raise AssertionError("camelCase-aware tokens should rank the relevant chunk higher")

    def test_semantic_ordering(self):
        from scripts.embeddings import _fallback_embed
        query = _fallback_embed("parse json configuration file")
        close = _fallback_embed("def parse_json_config(path): load configuration json")
        far = _fallback_embed("def render_button(label): draw a ui button")
        if _cos(query, close) <= _cos(query, far):
            raise AssertionError("Relevant text should score higher than unrelated text")

    def test_deterministic_across_hash_seeds(self):
        """
        The core regression test: the same text must embed identically under
        different PYTHONHASHSEED values (i.e. across processes). Builtin hash()
        would fail this; crc32 passes it.
        """
        pkg_root = Path(__file__).resolve().parent.parent
        snippet = (
            "import sys;"
            "sys.path.insert(0, r'{root}');"
            "from scripts.embeddings import _fallback_embed;"
            "v=_fallback_embed('authenticate the user session token');"
            "print(','.join('%.6f' % x for x in v))"
        ).format(root=str(pkg_root))

        def run(seed):
            env = dict(os.environ)
            env['PYTHONHASHSEED'] = seed
            out = subprocess.check_output([sys.executable, '-c', snippet], env=env)
            return out.decode().strip()

        first = run('0')
        second = run('12345')
        if first != second:
            raise AssertionError("Embeddings must not depend on PYTHONHASHSEED (cross-process stability)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
End-to-end test: the vector store indexes and searches non-Python source.
=========================================================================
Guards the fix that lets the semantic index work on TypeScript/JS monorepos,
not just Python. Runs entirely on the stdlib brute-force path (no FAISS/numpy).
"""

from pathlib import Path
import tempfile

import pytest


TS_SOURCE = """
export interface Invoice {
  id: string;
  lineItems: number[];
}

export function calculateInvoiceTotal(invoice: Invoice): number {
  return invoice.lineItems.reduce((sum, n) => sum + n, 0);
}

export function formatCurrency(amount: number): string {
  return '$' + amount.toFixed(2);
}
"""

PY_SOURCE = """
def render_widget(label):
    return f"<button>{label}</button>"
"""


@pytest.fixture
def ts_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "src").mkdir()
        (root / "src" / "billing.ts").write_text(TS_SOURCE)
        (root / "src" / "widget.py").write_text(PY_SOURCE)
        # Vendored dependency that must NOT be indexed.
        (root / "node_modules" / "dep").mkdir(parents=True)
        (root / "node_modules" / "dep" / "calculateInvoiceTotal.ts").write_text(TS_SOURCE)
        yield root


class TestMultiLanguageIndex:
    def _store(self, root):
        from scripts.vector_store import VectorStore
        store = VectorStore(root / ".mcp" / "vector_index")
        store.index_codebase(root)
        return store

    def test_indexes_typescript(self, ts_project):
        store = self._store(ts_project)
        if not store.chunks:
            raise AssertionError("Index should contain chunks from the TS file")
        languages = {c.language for c in store.chunks.values()}
        if "typescript" not in languages:
            raise AssertionError(f"TypeScript should be indexed; got {languages}")

    def test_excludes_node_modules(self, ts_project):
        store = self._store(ts_project)
        for chunk in store.chunks.values():
            if "node_modules" in Path(chunk.path).parts:
                raise AssertionError("node_modules must not be indexed")

    def test_search_finds_ts_function(self, ts_project):
        store = self._store(ts_project)
        results = store.search("calculate invoice total", k=5)
        if not results:
            raise AssertionError("Search should return results for a TS query")
        top_paths = " ".join(r.chunk.path for r in results)
        if "billing.ts" not in top_paths:
            raise AssertionError(f"Expected billing.ts in results; got {top_paths}")

    def test_persists_and_reloads(self, ts_project):
        from scripts.vector_store import VectorStore
        self._store(ts_project)
        reopened = VectorStore(ts_project / ".mcp" / "vector_index")
        if not reopened.load():
            raise AssertionError("Index should persist and reload from disk")
        if not reopened.chunks:
            raise AssertionError("Reloaded index should contain chunks")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

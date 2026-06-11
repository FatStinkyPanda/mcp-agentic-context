"""
Tests for incremental semantic re-indexing.
===========================================
Guards that unchanged files keep their embeddings (no re-embedding cost),
changed files are re-embedded, and deleted files are evicted - in both the
fingerprint-driven full path and the caller-driven changed_files path.
"""

from pathlib import Path
import os

import pytest

from scripts import vector_store


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "alpha.ts").write_text(
        "export function alphaLoader(id: string): string {\n  return 'a' + id;\n}\n")
    (root / "src" / "beta.ts").write_text(
        "export function betaSaver(id: string): string {\n  return 'b' + id;\n}\n")
    (root / "src" / "gamma.ts").write_text(
        "export function gammaHelper(id: string): string {\n  return 'g' + id;\n}\n")
    yield root


@pytest.fixture
def counting_embed(monkeypatch):
    """Count how many texts get embedded."""
    calls = {"texts": 0}
    real = vector_store.embed_texts

    def wrapper(texts):
        calls["texts"] += len(texts)
        return real(texts)

    monkeypatch.setattr(vector_store, "embed_texts", wrapper)
    return calls


class TestIncrementalFullPath:
    def test_unchanged_files_are_not_reembedded(self, project, tmp_path, counting_embed):
        store = vector_store.VectorStore(index_path=tmp_path / "idx")
        store.index_codebase(project)
        first_count = counting_embed["texts"]
        if first_count == 0:
            raise AssertionError("initial index must embed chunks")

        # No changes: second run must embed nothing.
        store2 = vector_store.VectorStore(index_path=tmp_path / "idx")
        store2.index_codebase(project)
        if counting_embed["texts"] != first_count:
            raise AssertionError(
                "no-change re-index re-embedded %d texts"
                % (counting_embed["texts"] - first_count))

    def test_changed_file_is_reembedded_and_searchable(self, project, tmp_path):
        store = vector_store.VectorStore(index_path=tmp_path / "idx")
        store.index_codebase(project)

        target = project / "src" / "alpha.ts"
        target.write_text(
            "export function alphaRenamedThing(id: string): string {\n"
            "  return 'changed' + id;\n}\n")
        os.utime(target, None)

        store2 = vector_store.VectorStore(index_path=tmp_path / "idx")
        store2.index_codebase(project)
        names = {c.name for c in store2.chunks.values()}
        if "alphaRenamedThing" not in names:
            raise AssertionError("changed file content missing after incremental re-index")
        if "alphaLoader" in names:
            raise AssertionError("stale chunk from the old file content survived")

    def test_deleted_file_is_evicted(self, project, tmp_path):
        store = vector_store.VectorStore(index_path=tmp_path / "idx")
        store.index_codebase(project)
        (project / "src" / "beta.ts").unlink()

        store2 = vector_store.VectorStore(index_path=tmp_path / "idx")
        store2.index_codebase(project)
        paths = {c.path for c in store2.chunks.values()}
        if any("beta.ts" in p for p in paths):
            raise AssertionError("deleted file's chunks must be evicted")

    def test_force_full_rebuilds(self, project, tmp_path, counting_embed):
        store = vector_store.VectorStore(index_path=tmp_path / "idx")
        store.index_codebase(project)
        first = counting_embed["texts"]
        store2 = vector_store.VectorStore(index_path=tmp_path / "idx")
        store2.index_codebase(project, force_full=True)
        if counting_embed["texts"] <= first:
            raise AssertionError("force_full must re-embed everything")


class TestChangedFilesPath:
    def test_changed_files_path_reconciles_deletions(self, project, tmp_path):
        store = vector_store.VectorStore(index_path=tmp_path / "idx")
        store.index_codebase(project)

        (project / "src" / "gamma.ts").unlink()
        touched = project / "src" / "alpha.ts"
        touched.write_text("export function alphaV2(): number { return 2; }\n")

        store2 = vector_store.VectorStore(index_path=tmp_path / "idx")
        store2.index_codebase(project, changed_files=[touched])
        paths = {c.path for c in store2.chunks.values()}
        if any("gamma.ts" in p for p in paths):
            raise AssertionError(
                "changed_files update must evict files deleted since last index")
        names = {c.name for c in store2.chunks.values()}
        if "alphaV2" not in names:
            raise AssertionError("changed file must be re-indexed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

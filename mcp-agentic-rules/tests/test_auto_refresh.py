"""
Tests for auto-fresh search.
============================
An agent that edits files and immediately searches must see the edits;
when nothing changed the refresh must do zero work (no save, no rebuild).
"""

from pathlib import Path
import os

import pytest

from scripts import vector_store
from scripts import serve as serve_mod


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / ".mcp").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "cart.ts").write_text(
        "export function calculateCartTotal(items: number[]): number {\n"
        "  return items.reduce((a, b) => a + b, 0);\n}\n")
    yield root


class TestRefresh:
    def test_fresh_index_needs_no_refresh(self, project, tmp_path):
        store = vector_store.VectorStore(index_path=tmp_path / "idx")
        store.index_codebase(project)
        if store.needs_refresh(project):
            raise AssertionError("index built moments ago must not be stale")
        if store.refresh(project):
            raise AssertionError("refresh with no changes must do no work")

    def test_refresh_picks_up_edits(self, project, tmp_path):
        store = vector_store.VectorStore(index_path=tmp_path / "idx")
        store.index_codebase(project)

        target = project / "src" / "cart.ts"
        target.write_text(
            "export function applyDiscountVoucher(total: number): number {\n"
            "  return total * 0.9;\n}\n")
        os.utime(target, None)

        if not store.needs_refresh(project):
            raise AssertionError("edited file must mark the index stale")
        if not store.refresh(project):
            raise AssertionError("refresh must run when files changed")
        names = {c.name for c in store.chunks.values()}
        if "applyDiscountVoucher" not in names:
            raise AssertionError("refreshed index missing the new symbol")
        if "calculateCartTotal" in names:
            raise AssertionError("stale symbol survived the refresh")

    def test_no_change_refresh_writes_nothing(self, project, tmp_path):
        store = vector_store.VectorStore(index_path=tmp_path / "idx")
        store.index_codebase(project)
        chunks_file = tmp_path / "idx" / "chunks.json"
        before = chunks_file.stat().st_mtime_ns
        store.refresh(project)
        after = chunks_file.stat().st_mtime_ns
        if before != after:
            raise AssertionError("no-change refresh must not rewrite the index files")


class TestDaemonAutoFresh:
    def test_search_sees_edits_made_after_daemon_start(self, project):
        old = os.getcwd()
        os.chdir(project)
        try:
            store = vector_store.VectorStore()
            store.index_codebase(project)

            server, _ = serve_mod.start_server(project)
            try:
                (project / "src" / "wish.ts").write_text(
                    "export function addToWishlist(id: string): boolean {\n"
                    "  return id.length > 0;\n}\n")
                resp = serve_mod.request(
                    project,
                    {"op": "search", "query": "add item to wishlist", "k": 5},
                    timeout=60.0)
                if not resp or not resp.get("ok"):
                    raise AssertionError("daemon search failed: %r" % resp)
                if not resp.get("refreshed"):
                    raise AssertionError("daemon must report it refreshed the index")
                paths = [r["path"] for r in resp.get("results", [])]
                if not any("wish.ts" in p for p in paths):
                    raise AssertionError(
                        "file created after daemon start must be searchable: %r" % paths)
            finally:
                server.shutdown()
                try:
                    serve_mod.serve_info_path(project).unlink()
                except OSError:
                    pass
        finally:
            os.chdir(old)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

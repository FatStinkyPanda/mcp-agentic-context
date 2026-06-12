"""
Update-system tests: version logic, cached checks, notice gating, and the
full update transaction (overlay + manifest + verify + rollback) end-to-end
against a real copy of the package. Heavy E2E cases are swarm-marked (they
run the engine selftest as the post-update verification).
"""

from pathlib import Path
import json
import os
import shutil
import zipfile

import pytest

from scripts import updater

PKG = Path(updater.__file__).resolve().parents[1]


@pytest.fixture
def upd_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_UPDATE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(updater, "RELEASE_FETCHER", None)
    monkeypatch.setattr(updater, "ZIP_FETCHER", None)
    return tmp_path


def _fake_release(tag, zip_src=None):
    def fetch():
        return {"tag": tag, "zipball": "fake://zip", "url": "https://x/releases/" + tag}
    return fetch


def test_version_parsing_and_compare():
    assert updater._parse_ver("v2.2.0") == (2, 2, 0)
    assert updater._parse_ver("2.10.3") > updater._parse_ver("v2.9.9")
    assert updater._parse_ver("garbage") == (0, 0, 0)
    assert updater.current_version(PKG) != "0.0.0"


def test_check_is_cached_within_ttl(upd_env, monkeypatch):
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return {"tag": "v99.0.0", "zipball": "fake://", "url": "u"}
    monkeypatch.setattr(updater, "RELEASE_FETCHER", counting)
    a1, cur, l1 = updater.check_update()
    a2, _, _ = updater.check_update()
    assert a1 is True and a2 is True and calls["n"] == 1, \
        "second check within the TTL must serve the cache"
    a3, _, _ = updater.check_update(force=True)
    assert a3 is True and calls["n"] == 2, "force must bypass the TTL"


def test_offline_check_is_silent_and_unknown(upd_env, monkeypatch):
    monkeypatch.setattr(updater, "RELEASE_FETCHER", lambda: None)
    available, cur, latest = updater.check_update(force=True)
    assert available is None and latest is None
    assert updater.notice() == "", "offline must never nag"


def test_notice_respects_auto_update_config(upd_env, monkeypatch):
    monkeypatch.setattr(updater, "RELEASE_FETCHER", _fake_release("v99.0.0"))
    updater.save_config({"auto_update": True})
    n_on = updater.notice()
    updater.save_config({"auto_update": False})
    n_off = updater.notice()
    assert "ENABLED" in n_on and "run `python" in n_on, \
        "default-on notice must authorize the agent to update"
    assert "DISABLED" in n_off and "ask the user" in n_off
    updater.save_config({"auto_update": True})
    monkeypatch.setattr(updater, "RELEASE_FETCHER",
                        _fake_release("v0.0.1"))
    (Path(os.environ["MCP_UPDATE_STATE_DIR"]) / "update_check.json").unlink()
    assert updater.notice() == "", "older releases must never notify"


def _build_payload_zip(tmp_path, version="99.0.0", break_engine=False):
    """A release zipball built from the REAL current package."""
    stage = tmp_path / "stage" / "repo-abc123" / "mcp-agentic-rules"
    shutil.copytree(PKG, stage, ignore=shutil.ignore_patterns(
        "__pycache__", ".venv", ".git-hooks", "tests"))
    init = stage / "scripts" / "__init__.py"
    init.write_text(init.read_text(encoding="utf-8").replace(
        updater.current_version(PKG), version), encoding="utf-8")
    if break_engine:
        (stage / "scripts" / "agent_collab.py").write_text(
            "raise RuntimeError('broken release')\n", encoding="utf-8")
    zpath = tmp_path / "release.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in stage.parent.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(tmp_path / "stage"))
    return zpath


def _install_copy(tmp_path):
    target = tmp_path / "proj" / "mcp-agentic-rules"
    shutil.copytree(PKG, target,
                    ignore=shutil.ignore_patterns("__pycache__", ".venv"))
    return target


@pytest.mark.swarm
def test_full_update_transaction_with_verification(upd_env, monkeypatch, tmp_path):
    zpath = _build_payload_zip(tmp_path, version="99.0.0")
    target = _install_copy(tmp_path)
    monkeypatch.setattr(updater, "RELEASE_FETCHER", _fake_release("v99.0.0"))
    monkeypatch.setattr(updater, "ZIP_FETCHER",
                        lambda url, dest: bool(shutil.copy2(zpath, dest)) or True)
    ok, lines = updater.do_update(pkg_root=target)
    text = "\n".join(lines)
    assert ok, text
    assert updater.current_version(target) == "99.0.0"
    assert "COLLAB_ENGINE_OK" in text or "verified" in text
    backups = list((target.parent / ".mcp-update-backup").glob("v*"))
    assert backups, "a backup of the previous install must exist"
    manifest = json.loads((target / updater.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["tag"] == "v99.0.0" and manifest["files"], \
        "the shipped-file manifest must be written for future deletions"


@pytest.mark.swarm
def test_broken_release_rolls_back_automatically(upd_env, monkeypatch, tmp_path):
    zpath = _build_payload_zip(tmp_path, version="99.0.0", break_engine=True)
    target = _install_copy(tmp_path)
    before = updater.current_version(target)
    monkeypatch.setattr(updater, "RELEASE_FETCHER", _fake_release("v99.0.0"))
    monkeypatch.setattr(updater, "ZIP_FETCHER",
                        lambda url, dest: bool(shutil.copy2(zpath, dest)) or True)
    ok, lines = updater.do_update(pkg_root=target)
    text = "\n".join(lines)
    assert not ok and "rolled back" in text, text
    assert updater.current_version(target) == before, \
        "a release that fails its own selftest must leave the install untouched"
    assert "broken release" not in (target / "scripts" / "agent_collab.py").read_text(
        encoding="utf-8")


def test_disabled_auto_update_requires_yes(upd_env, monkeypatch, tmp_path):
    target = _install_copy(tmp_path)
    monkeypatch.setattr(updater, "RELEASE_FETCHER", _fake_release("v99.0.0"))
    updater.save_config({"auto_update": False})
    ok, lines = updater.do_update(pkg_root=target)
    assert not ok and any("ask the user" in line for line in lines), \
        "disabled auto-update must stop unless --yes"

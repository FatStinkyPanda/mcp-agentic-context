#!/usr/bin/env python3
"""
Self-Update System
==================
Keeps any installed copy of mcp-agentic-context current with the latest
GitHub release — safely enough that AI AGENTS apply updates themselves.

    mcp update --check          is a newer release available? (cached, cheap)
    mcp update                  download + backup + overlay + VERIFY + (rollback)
    mcp update --status         versions, config, last check
    mcp update --enable-auto    (default) agents may update unprompted
    mcp update --disable-auto   agents must ask the user first

How agents SEE updates: session-start commands (state, autocontext, doctor,
collab status — CLI and MCP tool) print a one-line [UPDATE] notice when a
newer release exists. The notice states whether auto-update is enabled — when
it is (the default), the agent is authorized to run `mcp update` immediately.

Safety model: the current package is BACKED UP first; the new payload is
overlaid; upstream-deleted files are removed only when a shipped-file
manifest proves they were ours and they are locally unmodified; the NEW
engine's own selftest must print COLLAB_ENGINE_OK in a throwaway store or
everything rolls back automatically. Junction/symlink installs update the
canonical target. Git hooks are refreshed when MCP hooks are installed.

State (per-user): ~/.mcp/update_config.json   {"auto_update": true, "check_interval_hours": 24}
                  ~/.mcp/update_check.json    cached release probe
Network: gh CLI when available, anonymous GitHub API otherwise; offline is
always silent and non-fatal. Test seams: RELEASE_FETCHER, ZIP_FETCHER.
"""

from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

try:
    from scripts.agent_collab import atomic_write_json, _read_json
except ImportError:                       # direct invocation outside the package
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.modules.pop("scripts", None)
    from scripts.agent_collab import atomic_write_json, _read_json

REPO = "FatStinkyPanda/mcp-agentic-context"
DEFAULT_CONFIG = {"auto_update": True, "check_interval_hours": 24}
MANIFEST_NAME = ".mcp-manifest.json"
NOTIFY_COMMANDS = {"state", "project-state", "autocontext", "auto", "doctor",
                   "verify", "index-all"}

RELEASE_FETCHER = None      # tests inject: () -> {"tag","zipball","url"} | None
ZIP_FETCHER = None          # tests inject: (url, dest: Path) -> bool


def _pkg_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _state_dir() -> Path:
    d = Path(os.environ.get("MCP_UPDATE_STATE_DIR") or (Path.home() / ".mcp"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def current_version(pkg_root: Path = None) -> str:
    """Parsed from scripts/__init__.py — no import side effects."""
    init = (pkg_root or _pkg_root()) / "scripts" / "__init__.py"
    try:
        m = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']",
                      init.read_text(encoding="utf-8"))
        return m.group(1) if m else "0.0.0"
    except OSError:
        return "0.0.0"


def _parse_ver(tag: str):
    nums = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in (nums + ["0", "0", "0"])[:3])


def load_config() -> dict:
    cfg = _read_json(_state_dir() / "update_config.json") or {}
    return {**DEFAULT_CONFIG, **cfg}


def save_config(cfg: dict):
    atomic_write_json(_state_dir() / "update_config.json", cfg)


def _fetch_latest_release(timeout: float = 6.0):
    """gh CLI first (authenticated rate limits), anonymous API second.
    Returns {"tag","zipball","url"} or None — NEVER raises."""
    exe = shutil.which("gh")
    if exe:
        try:
            proc = subprocess.run(
                [exe, "api", "repos/%s/releases/latest" % REPO],
                capture_output=True, text=True, timeout=timeout * 3,
                encoding="utf-8", errors="replace")
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                return {"tag": data.get("tag_name", ""),
                        "zipball": data.get("zipball_url", ""),
                        "url": data.get("html_url", "")}
        except Exception:
            pass
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/releases/latest" % REPO,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "mcp-agentic-context-updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"tag": data.get("tag_name", ""),
                "zipball": data.get("zipball_url", ""),
                "url": data.get("html_url", "")}
    except Exception:
        return None


def check_update(force: bool = False):
    """(available, current, latest_info). available is None when unknown
    (offline and no usable cache). Network at most once per TTL."""
    cur = current_version()
    cache_path = _state_dir() / "update_check.json"
    cache = _read_json(cache_path)
    ttl = float(load_config().get("check_interval_hours", 24)) * 3600
    if not force and cache and (time.time() - cache.get("t", 0)) < ttl:
        latest = cache.get("latest") or {}
        if not latest.get("tag"):
            return None, cur, None
        return _parse_ver(latest["tag"]) > _parse_ver(cur), cur, latest
    fetch = RELEASE_FETCHER or _fetch_latest_release
    info = fetch()
    atomic_write_json(cache_path, {"t": time.time(), "latest": info or {}})
    if not info or not info.get("tag"):
        if cache and (cache.get("latest") or {}).get("tag"):
            latest = cache["latest"]
            return _parse_ver(latest["tag"]) > _parse_ver(cur), cur, latest
        return None, cur, None
    return _parse_ver(info["tag"]) > _parse_ver(cur), cur, info


def notice() -> str:
    """The one-line update notice for session-start surfaces ('' when current
    or unknown). Cheap: network only when the check cache expired."""
    try:
        available, cur, latest = check_update()
    except Exception:
        return ""
    if not available or not latest:
        return ""
    if load_config().get("auto_update", True):
        return ("[UPDATE] mcp-agentic-context %s is available (you have v%s). "
                "Auto-update is ENABLED — run `python mcp-agentic-rules/mcp.py update` "
                "now (backs up, self-verifies, auto-rolls-back on failure)."
                % (latest["tag"], cur))
    return ("[UPDATE] mcp-agentic-context %s is available (you have v%s). "
            "Auto-update is DISABLED — ask the user before running "
            "`python mcp-agentic-rules/mcp.py update --yes`."
            % (latest["tag"], cur))


def maybe_notify(stream=None):
    """Print the notice (stderr by default so machine-parsed stdout stays
    clean). Swallows everything — a notifier must never break a command."""
    try:
        line = notice()
        if line:
            print(line, file=stream or sys.stderr)
    except Exception:
        pass


def _download_zip(url: str, dest: Path) -> bool:
    try:
        import urllib.request
        req = urllib.request.Request(
            url, headers={"User-Agent": "mcp-agentic-context-updater"})
        with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
        return True
    except Exception:
        return False


def _payload_files(payload: Path):
    for p in payload.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            yield p.relative_to(payload)


def _verify(pkg: Path) -> bool:
    """The new engine must prove itself: COLLAB_ENGINE_OK in a throwaway store."""
    store = tempfile.mkdtemp(prefix="update-verify-")
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(pkg / "scripts" / "agent_collab.py"),
             "selftest"],
            capture_output=True, text=True, timeout=600, cwd=str(pkg.parent),
            encoding="utf-8", errors="replace",
            env={**os.environ, "MCP_NSYNC_PATH": store, "MCP_NSYNC_AUTOSYNC": "0"})
        return proc.returncode == 0 and "COLLAB_ENGINE_OK" in (proc.stdout or "")
    except Exception:
        return False
    finally:
        shutil.rmtree(store, ignore_errors=True)


def do_update(pkg_root: Path = None, force: bool = False, assume_yes: bool = False):
    """The full safe-update transaction. Returns (ok, lines)."""
    lines = []
    pkg = Path(pkg_root) if pkg_root else _pkg_root()
    real = pkg.resolve()
    if str(real) != str(pkg):
        lines.append("[NOTE] %s is a link — updating the canonical install at %s"
                     % (pkg, real))
    pkg = real
    available, cur, latest = check_update(force=True)
    if available is None:
        return False, lines + ["cannot reach GitHub to check releases — try again online"]
    if not available and not force:
        return True, lines + ["already up to date (v%s)" % cur]
    if not load_config().get("auto_update", True) and not assume_yes:
        return False, lines + [
            "auto-update is DISABLED — ask the user, then run `mcp update --yes`"]
    tag = latest["tag"]
    lines.append("updating v%s -> %s ..." % (cur, tag))

    workdir = Path(tempfile.mkdtemp(prefix="mcp-update-"))
    try:
        zip_path = workdir / "release.zip"
        fetch_zip = ZIP_FETCHER or _download_zip
        if not fetch_zip(latest.get("zipball", ""), zip_path):
            return False, lines + ["download failed: %s" % latest.get("zipball", "")]
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(workdir / "x")
        payload = next((workdir / "x").glob("*/mcp-agentic-rules"), None)
        if payload is None:
            return False, lines + ["release zip carries no mcp-agentic-rules/ payload"]

        backups_root = pkg.parent / ".mcp-update-backup"
        backup = backups_root / ("v%s-%d" % (cur, int(time.time())))
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pkg, backup,
                        ignore=shutil.ignore_patterns("__pycache__", ".venv"))
        lines.append("backup: %s (gitignore .mcp-update-backup/)" % backup)

        new_files = sorted(str(r).replace("\\", "/") for r in _payload_files(payload))
        for rel in new_files:
            src, dst = payload / rel, pkg / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        removed = []
        old_manifest = _read_json(pkg / MANIFEST_NAME)
        for rel in (old_manifest or {}).get("files", []):
            if rel in new_files:
                continue
            cur_f, bak_f = pkg / rel, backup / rel
            # ours before, gone upstream, and locally unmodified -> remove
            if cur_f.is_file() and bak_f.is_file() \
                    and cur_f.read_bytes() == bak_f.read_bytes():
                try:
                    cur_f.unlink()
                    removed.append(rel)
                except OSError:
                    pass
        if old_manifest is None:
            lines.append("[NOTE] no shipped-file manifest yet (first managed update) — "
                         "upstream-deleted files were left in place")
        elif removed:
            lines.append("removed %d upstream-deleted file(s)" % len(removed))
        atomic_write_json(pkg / MANIFEST_NAME, {"tag": tag, "files": new_files})

        lines.append("verifying the new engine (selftest, throwaway store)...")
        if not _verify(pkg):
            failed = backups_root / ("failed-%s-%d" % (tag, int(time.time())))
            shutil.copytree(pkg, failed,
                            ignore=shutil.ignore_patterns("__pycache__", ".venv"))
            for rel in new_files:                       # restore: backup is truth
                tgt = pkg / rel
                bak_f = backup / rel
                if bak_f.is_file():
                    shutil.copy2(bak_f, tgt)
                else:
                    try:
                        tgt.unlink()
                    except OSError:
                        pass
            if old_manifest is not None:
                atomic_write_json(pkg / MANIFEST_NAME, old_manifest)
            else:
                (pkg / MANIFEST_NAME).unlink(missing_ok=True)
            return False, lines + [
                "VERIFY FAILED — rolled back to v%s. The broken payload is kept at %s "
                "for diagnosis; please report this release." % (cur, failed)]
        lines.append("verified: COLLAB_ENGINE_OK")

        hooks = pkg.parent / ".git" / "hooks" / "pre-push"
        try:
            if hooks.is_file() and "[MCP]" in hooks.read_text(encoding="utf-8",
                                                              errors="replace"):
                subprocess.run([sys.executable, str(pkg / "mcp.py"), "setup", "--hooks"],
                               capture_output=True, timeout=120)
                lines.append("git hooks refreshed")
        except Exception:
            pass
        keep = sorted(backups_root.glob("v*"), key=lambda p: p.stat().st_mtime)[:-2]
        for old in keep:                                # retain the 2 newest backups
            shutil.rmtree(old, ignore_errors=True)
        return True, lines + ["updated to %s (was v%s)" % (tag, cur)]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    args = sys.argv[1:]
    if "--enable-auto" in args:
        save_config({**load_config(), "auto_update": True})
        print("[OK] auto-update ENABLED — agents may apply updates unprompted")
        return 0
    if "--disable-auto" in args:
        save_config({**load_config(), "auto_update": False})
        print("[OK] auto-update DISABLED — agents must ask before updating")
        return 0
    if "--status" in args or "--check" in args:
        available, cur, latest = check_update(force="--check" in args)
        cfg = load_config()
        print("installed: v%s" % cur)
        print("latest:    %s" % ((latest or {}).get("tag") or "(unknown — offline?)"))
        print("auto-update: %s" % ("ENABLED (default)" if cfg.get("auto_update", True)
                                   else "DISABLED"))
        if available:
            print("UPDATE_AVAILABLE %s — run `python mcp-agentic-rules/mcp.py update`"
                  % latest["tag"])
        elif available is False:
            print("up to date")
        return 0
    ok, lines = do_update(force="--force" in args, assume_yes="--yes" in args)
    for line in lines:
        print(line)
    print("[OK] update complete" if ok else "[FAIL] update not applied")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

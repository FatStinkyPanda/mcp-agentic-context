"""
JS/TS Toolchain Bridge
======================
Detects a JavaScript/TypeScript project and runs the project's OWN quality
tools (eslint, tsc, pnpm audit), merging their findings into MCP reports.
The repo's configured toolchain understands its code far better than any
generic analyzer, so on JS/TS projects review/security delegate to it.

All parsers are pure functions over tool output so they can be tested
without node installed.
"""

from pathlib import Path
from typing import Dict, List, Optional
import json
import os
import re
import subprocess

from .utils import Console

DEFAULT_TIMEOUT = int(os.environ.get("MCP_JS_TOOL_TIMEOUT", "180"))
MAX_FINDINGS = 500


def detect_js_project(root: Path) -> Dict[str, bool]:
    """
    Inspect package.json (and lockfiles) to learn which tools the project
    itself declares. Returns {} for non-JS projects.
    """
    pkg_path = Path(root) / "package.json"
    if not pkg_path.exists():
        return {}
    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            pkg = json.load(f)
    except Exception:
        return {}

    deps = {}
    for section in ("dependencies", "devDependencies"):
        section_value = pkg.get(section)
        if isinstance(section_value, dict):
            deps.update(section_value)
    scripts = pkg.get("scripts") or {}
    script_text = " ".join(str(v) for v in scripts.values())

    return {
        "js_project": True,
        "eslint": "eslint" in deps or "eslint" in script_text,
        "typescript": "typescript" in deps or "tsc" in script_text,
        "pnpm": (Path(root) / "pnpm-lock.yaml").exists()
                or (Path(root) / "pnpm-workspace.yaml").exists(),
    }


def runner_prefix(root: Path) -> List[str]:
    """Command prefix that executes a local node tool the project's way."""
    info = detect_js_project(root)
    if info.get("pnpm"):
        return ["pnpm", "exec"]
    return ["npx", "--no-install"]


def parse_eslint_json(text: str) -> List[dict]:
    """
    Parse `eslint --format json` output into normalized findings:
    {file, line, severity ('error'|'warning'), rule, message}.
    """
    findings: List[dict] = []
    text = text.strip()
    if not text:
        return findings
    # eslint may print npm/pnpm banner noise before the JSON array.
    start = text.find("[")
    if start < 0:
        return findings
    try:
        results = json.loads(text[start:])
    except json.JSONDecodeError:
        return findings
    for file_result in results:
        path = file_result.get("filePath", "")
        for msg in file_result.get("messages", []):
            findings.append({
                "file": path,
                "line": int(msg.get("line") or 0),
                "severity": "error" if msg.get("severity") == 2 else "warning",
                "rule": msg.get("ruleId") or "eslint",
                "message": msg.get("message", ""),
            })
            if len(findings) >= MAX_FINDINGS:
                return findings
    return findings


TSC_LINE = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\):\s*"
    r"(?P<sev>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.*)$")


def parse_tsc_output(text: str) -> List[dict]:
    """
    Parse `tsc --noEmit --pretty false` output into normalized findings:
    {file, line, severity, rule, message}.
    """
    findings: List[dict] = []
    for line in text.splitlines():
        match = TSC_LINE.match(line.strip())
        if match:
            findings.append({
                "file": match.group("file"),
                "line": int(match.group("line")),
                "severity": match.group("sev"),
                "rule": match.group("code"),
                "message": match.group("msg"),
            })
            if len(findings) >= MAX_FINDINGS:
                break
    return findings


def parse_pnpm_audit_json(text: str) -> List[dict]:
    """
    Parse `pnpm audit --json` output into normalized findings:
    {severity, title, module, url}.
    """
    findings: List[dict] = []
    text = text.strip()
    start = text.find("{")
    if start < 0:
        return findings
    try:
        data = json.loads(text[start:])
    except json.JSONDecodeError:
        return findings
    advisories = data.get("advisories") or {}
    for adv in advisories.values():
        findings.append({
            "severity": adv.get("severity", "info"),
            "title": adv.get("title", ""),
            "module": adv.get("module_name", ""),
            "url": adv.get("url", ""),
        })
    return findings


def _run(cmd: List[str], root: Path, timeout: int) -> Optional[str]:
    """Run a toolchain command, returning combined output or None on failure
    to launch. Non-zero exits still return output (linters exit non-zero
    when they find issues - that IS the result)."""
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True,
            timeout=timeout, shell=(os.name == "nt"))
        return (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        Console.warn(f"Could not run {' '.join(cmd)}: {e}")
        return None


def run_eslint(root: Path, timeout: int = DEFAULT_TIMEOUT,
               target: Optional[Path] = None) -> List[dict]:
    """Run the project's eslint over the repo (or one file); [] when
    unavailable."""
    eslint_target = str(target) if target else "."
    out = _run(runner_prefix(root) + ["eslint", eslint_target, "--format", "json"],
               root, timeout)
    return parse_eslint_json(out) if out else []


def run_tsc(root: Path, timeout: int = DEFAULT_TIMEOUT) -> List[dict]:
    """Run the project's tsc --noEmit; [] when unavailable."""
    out = _run(runner_prefix(root) + ["tsc", "--noEmit", "--pretty", "false"],
               root, timeout)
    return parse_tsc_output(out) if out else []


def run_pnpm_audit(root: Path, timeout: int = DEFAULT_TIMEOUT) -> List[dict]:
    """Run pnpm audit --json (dependency vulnerabilities); [] if unavailable."""
    out = _run(["pnpm", "audit", "--json"], root, timeout)
    return parse_pnpm_audit_json(out) if out else []

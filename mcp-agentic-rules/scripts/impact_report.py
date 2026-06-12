#!/usr/bin/env python3
"""
Agent Impact Report
===================
Markdown impact report for GitHub-native collaboration: what a set of files
(mentioned in an issue body, changed in a PR diff, or given explicitly)
touches across the codebase — direct importers, transitive dependents,
affected tests — plus a CONFLICT RADAR comparing against every other open
`in-progress` issue so two agents learn they overlap BEFORE they collide.

Used by .github/workflows/agent-issue-impact.yml and agent-pr-impact.yml;
works locally the same way. Emits markdown on stdout (build chatter goes to
stderr); the leading marker comment lets workflows upsert a single comment.

Usage:
    python mcp-agentic-rules/scripts/impact_report.py --from-env ISSUE_BODY --issue 7 --radar
    python mcp-agentic-rules/scripts/impact_report.py --diff origin/master...HEAD --radar
    python mcp-agentic-rules/scripts/impact_report.py --paths src/a.py lib/b.ts
"""

from contextlib import redirect_stdout
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.impact import build_dependency_graph              # noqa: E402
from scripts.agent_collab import extract_paths                 # noqa: E402

MARKER = "<!-- agent-impact -->"
CAP = 10           # listed items per section; counts always show the full total
GH_TIMEOUT = 30


def _norm(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def resolve_mentions(graph, mentions):
    """Map free-text path mentions onto graph file keys: exact match first,
    then unique-suffix match (issue bodies rarely write full repo paths)."""
    by_norm = {_norm(k): k for k in graph.all_files}
    resolved, missing = {}, []
    for m in mentions:
        nm = _norm(m)
        if nm in by_norm:
            resolved[m] = [by_norm[nm]]
            continue
        hits = sorted(k for nk, k in by_norm.items() if nk.endswith("/" + nm))
        if hits:
            resolved[m] = hits[:3]
        else:
            missing.append(m)
    return resolved, missing


def impact_set(graph, keys):
    """Union of transitive dependents over the given file keys."""
    out = set()
    for k in keys:
        out |= graph.get_transitive_dependents(k)
    return out


def _gh_json(gh_args):
    exe = shutil.which("gh")
    if not exe:
        return None
    try:
        proc = subprocess.run([exe] + gh_args, capture_output=True, text=True,
                              timeout=GH_TIMEOUT, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def radar(graph, our_keys, our_impact, skip_issue):
    """Other open in-progress issues whose impact sets intersect ours."""
    issues = _gh_json(["issue", "list", "--state", "open", "--label", "in-progress",
                       "--limit", "50", "--json", "number,title,body,url"])
    if issues is None:
        return None                                   # gh absent/unauthed — radar offline
    ours = set(our_keys) | set(our_impact)
    overlaps = []
    for it in issues:
        n = it.get("number")
        if skip_issue is not None and n == skip_issue:
            continue
        resolved, _ = resolve_mentions(graph, extract_paths(it.get("body") or ""))
        their_keys = [k for ks in resolved.values() for k in ks]
        theirs = set(their_keys) | impact_set(graph, their_keys)
        common = sorted(ours & theirs)
        if common:
            overlaps.append((n, it.get("title", ""), it.get("url", ""), common))
    return overlaps


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-env", metavar="VAR",
                    help="extract file mentions from the text in this env var")
    ap.add_argument("--paths", nargs="*", default=None, help="explicit file paths")
    ap.add_argument("--diff", metavar="RANGE",
                    help="paths from `git diff --name-only RANGE`")
    ap.add_argument("--issue", type=int, default=None,
                    help="issue number (header + radar self-exclusion)")
    ap.add_argument("--title", default=None, help="report title override")
    ap.add_argument("--radar", action="store_true",
                    help="scan other open in-progress issues for impact overlap")
    args = ap.parse_args()

    mentions = []
    if args.from_env:
        mentions = extract_paths(os.environ.get(args.from_env, ""))
    elif args.diff:
        proc = subprocess.run(["git", "diff", "--name-only", args.diff],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            print("git diff failed: %s" % proc.stderr.strip(), file=sys.stderr)
            return 1
        mentions = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    elif args.paths is not None:
        mentions = args.paths
    else:
        ap.error("one of --from-env / --diff / --paths is required")

    title = args.title or ("Agent impact report for issue #%d" % args.issue
                           if args.issue else "Agent impact report")
    lines = [MARKER, "## %s" % title, ""]

    if not mentions:
        lines += ["No file paths detected in the input — nothing to analyze.",
                  "Mention concrete paths (e.g. `src/module.py`) to get an impact map."]
        print("\n".join(lines))
        return 0

    with redirect_stdout(sys.stderr):                 # graph build chatter -> CI log
        graph = build_dependency_graph(Path.cwd())

    resolved, missing = resolve_mentions(graph, mentions)
    our_keys = [k for ks in resolved.values() for k in ks]

    for mention, keys in resolved.items():
        for key in keys:
            nk = _norm(key)
            direct = sorted(_norm(d) for d in graph.get_dependents(key))
            transitive = sorted(_norm(d) for d in graph.get_transitive_dependents(key))
            tests = [d for d in transitive if "test" in d.lower()]
            lines.append("### `%s`" % nk)
            if not transitive:
                lines.append("- no known dependents (leaf file)")
            else:
                lines.append("- **%d direct importer(s)**: %s"
                             % (len(direct),
                                ", ".join("`%s`" % d for d in direct[:CAP])
                                + (" …" if len(direct) > CAP else "")))
                lines.append("- **%d transitive dependent(s)** in total" % len(transitive))
                if tests:
                    lines.append("- **affected tests (%d)**: %s"
                                 % (len(tests),
                                    ", ".join("`%s`" % t for t in tests[:CAP])
                                    + (" …" if len(tests) > CAP else "")))
            lines.append("")

    if missing:
        lines.append("Mentioned but not found in the repo: "
                     + ", ".join("`%s`" % m for m in missing[:CAP]))
        lines.append("")

    if args.radar:
        overlaps = radar(graph, our_keys, impact_set(graph, our_keys), args.issue)
        lines.append("### Conflict radar")
        if overlaps is None:
            lines.append("(radar offline — gh CLI unavailable)")
        elif not overlaps:
            lines.append("No other open `in-progress` issue overlaps this impact set.")
        else:
            for n, ititle, url, common in overlaps:
                lines.append("- **OVERLAP with [#%d](%s)** (%s) — shared impact: %s"
                             % (n, url, ititle,
                                ", ".join("`%s`" % _norm(c) for c in common[:5])
                                + (" …" if len(common) > 5 else "")))
        lines.append("")

    lines.append("_Generated by `mcp impact` (mcp-agentic-context agent collab)._")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

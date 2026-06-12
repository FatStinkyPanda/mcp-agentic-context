#!/usr/bin/env python3
"""
Swarm Reconciler v1 — the closer of last resort
===============================================
Crashed agents leave GitHub-side residue the local janitor cannot reach:
issues that lost their `state:available` seed, and duplicate marker-comment
families from racing workflow runs. This reconciler is LEVEL-TRIGGERED and
IDEMPOTENT: it reads the current state (ONE batched GraphQL query live, or a
--state-file fixture in tests), computes the delta, and applies it — running
it twice in a row is always a no-op the second time.

v1 passes (deliberately small — structural enforcement lives in the engine):
  SEED    open issues with NO state:* / in-progress / agent:* label get
          `state:available` so they re-enter the claimable pool.
  DEDUPE  comment families starting with `<!-- agent-impact -->` keep the
          LOWEST comment id; later duplicates (concurrent run races) are
          deleted.

Every mutation is printed as one ndjson line (the audit log the Action run
captures). --dry-run logs without mutating. Driven by GITHUB_TOKEN in
.github/workflows/agent-reconcile.yml (singleton concurrency, cron + manual
dispatch + repository_dispatch[agent-sync]).

Usage:
    python scripts/swarm_reconcile.py --live [--repo OWNER/NAME] [--dry-run]
    python scripts/swarm_reconcile.py --state-file fixture.json [--dry-run]
"""

from pathlib import Path
import argparse
import json
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.modules.pop("scripts", None)
from scripts import agent_collab as ac                          # noqa: E402

MARKER = "<!-- agent-impact -->"
DASHBOARD_LABEL = "swarm-dashboard"
DASHBOARD_TITLE = "Swarm Dashboard"
GRAPHQL_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    latestRelease { tagName }
    issues(states: OPEN, first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number
        title
        body
        labels(first: 20) { nodes { name } }
        comments(first: 100) { nodes { databaseId body } }
      }
    }
  }
}
"""

GH_RUNNER = None        # tests inject; defaults to agent_collab.GH_RUNNER


def _run(gh_args):
    return (GH_RUNNER or ac.GH_RUNNER)(gh_args)


def gather_live(repo: str):
    """ONE batched read for everything the passes need. Returns the
    normalized state dict or None with an error message."""
    owner, name = repo.split("/", 1)
    ok, out = _run(["api", "graphql",
                    "-f", "query=" + GRAPHQL_QUERY,
                    "-f", "owner=" + owner, "-f", "name=" + name])
    if not ok:
        return None, "graphql read failed: %s" % out
    try:
        repo_data = json.loads(out)["data"]["repository"]
        nodes = repo_data["issues"]["nodes"]
    except Exception as e:
        return None, "unparseable graphql payload: %s" % e
    return {"latest_release": ((repo_data.get("latestRelease") or {}).get("tagName") or ""),
            "issues": [
                {"number": n["number"], "title": n.get("title") or "",
                 "body": n.get("body") or "",
                 "labels": [x["name"] for x in n["labels"]["nodes"]],
                 "comments": [{"id": c["databaseId"], "body": c.get("body") or ""}
                              for c in n["comments"]["nodes"]]}
                for n in nodes]}, None


def _issue_facts(issue: dict):
    """Coordination facts for one issue (board rows + radar input)."""
    labels = set(issue.get("labels", []))
    form = ac.parse_issue_form(issue.get("body") or "")
    agents = sorted(x[len("agent:"):] for x in labels if x.startswith("agent:"))
    paths = (form.get("paths")
             or ac.extract_paths(issue.get("body") or ""))[:8]
    if "in-progress" in labels:
        st = "in-progress"
    elif "state:review" in labels:
        st = "review"
    elif "state:available" in labels:
        st = "ready"
    else:
        st = "unlabeled"
    return {"n": issue["number"], "title": issue.get("title", ""), "state": st,
            "agents": agents, "paths": paths,
            "depends": form.get("depends") or [], "prio": form.get("priority", "")}


def render_dashboard(state: dict) -> str:
    """The board body. Deterministic for a given state EXCEPT the timestamp
    line (excluded from change detection) — so a steady fleet re-plans to
    zero dashboard actions."""
    import time as _t
    rows = [_issue_facts(i) for i in state.get("issues", [])
            if DASHBOARD_LABEL not in i.get("labels", [])]
    rows.sort(key=lambda r: r["n"])
    open_nums = {r["n"] for r in rows}
    lines = ["<!-- swarm-dashboard -->",
             "# Swarm Dashboard",
             "_Maintained by agent-reconcile — do not edit. Updated: %s_"
             % _t.strftime("%Y-%m-%d %H:%M UTC", _t.gmtime()),
             "",
             "## Work"]
    if rows:
        lines += ["| # | task | state | agent(s) | priority |",
                  "|---|------|-------|----------|----------|"]
        for r in rows:
            blocked = [d for d in r["depends"] if d in open_nums]
            st = ("blocked by %s" % ", ".join("#%d" % d for d in blocked)
                  if blocked and r["state"] == "ready" else r["state"])
            lines.append("| #%d | %s | %s | %s | %s |"
                         % (r["n"], r["title"][:60], st,
                            ", ".join(r["agents"]) or "—", r["prio"] or "—"))
    else:
        lines.append("(no open agent tasks — file one with the Agent task issue form)")
    lines += ["", "## Conflict radar"]
    active = [r for r in rows if r["state"] == "in-progress"]
    overlaps = []
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            shared = sorted(set(a["paths"]) & set(b["paths"]))
            if shared:
                overlaps.append("- #%d ↔ #%d both touch: %s"
                                % (a["n"], b["n"], ", ".join("`%s`" % s
                                                             for s in shared[:5])))
    lines += overlaps or ["(no overlapping in-progress work)"]
    lines += ["", "## Release",
              "latest: **%s** — installs self-update at session start "
              "(auto-update default-on; `mcp update --status`)"
              % (state.get("latest_release") or "(none)")]
    return "\n".join(lines)


def _board_core(body: str) -> str:
    """The change-detection view of a board body: timestamp line excluded."""
    return "\n".join(line for line in (body or "").splitlines()
                     if not line.startswith("_Maintained by"))


def plan(state: dict):
    """The level-triggered delta: what must change to make GitHub consistent.
    Pure function of the state — this is what makes the reconciler idempotent
    and unit-testable."""
    actions = []
    dashboard = None
    for issue in state.get("issues", []):
        labels = set(issue.get("labels", []))
        if DASHBOARD_LABEL in labels:
            dashboard = issue
            continue                                 # the board is never seeded
        coordinated = ("in-progress" in labels
                       or any(x.startswith("state:") for x in labels)
                       or any(x.startswith("agent:") for x in labels))
        if not coordinated:
            actions.append({"action": "seed", "issue": issue["number"],
                            "label": "state:available"})
        family = sorted(c["id"] for c in issue.get("comments", [])
                        if str(c.get("body", "")).startswith(MARKER))
        for dup in family[1:]:                       # keep the LOWEST id
            actions.append({"action": "delete_comment", "issue": issue["number"],
                            "comment": dup})
    # Render the board from the PROJECTED post-mutation state (seeds applied),
    # so one pass converges — otherwise every seeding run leaves a board that
    # is stale until the next cron tick.
    seeded = {a["issue"] for a in actions if a["action"] == "seed"}
    projected = dict(state, issues=[
        (dict(i, labels=list(i.get("labels", [])) + ["state:available"])
         if i["number"] in seeded else i)
        for i in state.get("issues", [])])
    board = render_dashboard(projected)
    if dashboard is None:
        actions.append({"action": "dashboard_create", "body": board})
    elif _board_core(dashboard.get("body", "")) != _board_core(board):
        actions.append({"action": "dashboard_update", "issue": dashboard["number"],
                        "body": board})
    return actions


def apply(actions, repo: str, dry_run: bool = False):
    """Execute (or just log) the plan. Mutations are individually idempotent:
    re-adding a label is a no-op, deleting a deleted comment 404s harmlessly."""
    applied = 0
    for act in actions:
        logged = {k: (v if k != "body" else "<%d chars>" % len(v))
                  for k, v in act.items()}
        print(json.dumps({**logged, "dry_run": dry_run}, ensure_ascii=False))
        if dry_run:
            continue
        if act["action"] == "seed":
            ok, out = _run(["issue", "edit", str(act["issue"]),
                            "--add-label", act["label"]])
            if not ok:           # the label may not exist yet on fresh repos
                _run(["label", "create", act["label"], "--color", "0E8A16", "--force"])
                ok, out = _run(["issue", "edit", str(act["issue"]),
                                "--add-label", act["label"]])
        elif act["action"] == "delete_comment":
            ok, out = _run(["api", "-X", "DELETE",
                            "repos/%s/issues/comments/%d" % (repo, act["comment"])])
        elif act["action"] == "dashboard_update":
            ok, out = _run(["issue", "edit", str(act["issue"]),
                            "--body", act["body"]])
        elif act["action"] == "dashboard_create":
            _run(["label", "create", DASHBOARD_LABEL, "--color", "5319E7", "--force"])
            ok, out = _run(["issue", "create", "--title", DASHBOARD_TITLE,
                            "--label", DASHBOARD_LABEL, "--body", act["body"]])
            if ok:
                m = re.search(r"/issues/(\d+)", str(out))
                if m:
                    _run(["issue", "pin", m.group(1)])     # best-effort
        else:
            ok = False
        if ok:
            applied += 1
    return applied


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--live", action="store_true", help="read via gh (one GraphQL query)")
    src.add_argument("--state-file", help="fixture JSON instead of GitHub (tests)")
    ap.add_argument("--repo", default="FatStinkyPanda/mcp-agentic-context")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.state_file:
        state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
    else:
        state, err = gather_live(args.repo)
        if state is None:
            print("[FAIL] " + err)
            return 1
    actions = plan(state)
    applied = apply(actions, args.repo, dry_run=args.dry_run)
    print("[OK] reconcile: %d issue(s) read, %d action(s) %s"
          % (len(state.get("issues", [])), len(actions),
             "planned (dry-run)" if args.dry_run else "applied (%d ok)" % applied))
    return 0


if __name__ == "__main__":
    sys.exit(main())

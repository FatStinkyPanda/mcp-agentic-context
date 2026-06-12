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
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.modules.pop("scripts", None)
from scripts import agent_collab as ac                          # noqa: E402

MARKER = "<!-- agent-impact -->"
GRAPHQL_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number
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
        nodes = json.loads(out)["data"]["repository"]["issues"]["nodes"]
    except Exception as e:
        return None, "unparseable graphql payload: %s" % e
    return {"issues": [
        {"number": n["number"],
         "labels": [x["name"] for x in n["labels"]["nodes"]],
         "comments": [{"id": c["databaseId"], "body": c.get("body") or ""}
                      for c in n["comments"]["nodes"]]}
        for n in nodes]}, None


def plan(state: dict):
    """The level-triggered delta: what must change to make GitHub consistent.
    Pure function of the state — this is what makes the reconciler idempotent
    and unit-testable."""
    actions = []
    for issue in state.get("issues", []):
        labels = set(issue.get("labels", []))
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
    return actions


def apply(actions, repo: str, dry_run: bool = False):
    """Execute (or just log) the plan. Mutations are individually idempotent:
    re-adding a label is a no-op, deleting a deleted comment 404s harmlessly."""
    applied = 0
    for act in actions:
        print(json.dumps({**act, "dry_run": dry_run}, ensure_ascii=False))
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

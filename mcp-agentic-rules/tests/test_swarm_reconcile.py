"""
Reconciler tests: the plan() delta is a pure function (idempotency provable),
seeding only touches uncoordinated issues, dedupe keeps the lowest marker
comment, dry-run never mutates, and applying the plan converges (re-planning
after apply yields zero actions).
"""

import json

import pytest

from scripts import swarm_reconcile as sr

FIXTURE = {
    "issues": [
        {"number": 1, "labels": [], "comments": []},                       # -> seed
        {"number": 2, "labels": ["state:review"], "comments": []},         # coordinated
        {"number": 3, "labels": ["in-progress", "agent:zz"], "comments": []},
        {"number": 4, "labels": ["bug"], "comments": [                     # -> seed + dedupe
            {"id": 11, "body": sr.MARKER + "\nreport A"},
            {"id": 22, "body": sr.MARKER + "\nreport B (racing duplicate)"},
            {"id": 33, "body": "a human comment — untouchable"},
            {"id": 44, "body": sr.MARKER + "\nreport C (racing duplicate)"},
        ]},
        {"number": 5, "labels": ["state:available"], "comments": [         # already seeded
            {"id": 55, "body": sr.MARKER + "\nsingleton report"},          # no dupes
        ]},
    ]
}


def _seed_actions(actions):
    return sorted(a["issue"] for a in actions if a["action"] == "seed")


def test_plan_seeds_only_uncoordinated_issues():
    actions = sr.plan(FIXTURE)
    assert _seed_actions(actions) == [1, 4], "exactly the label-less issues get re-seeded"


def test_dashboard_created_when_absent_and_excluded_from_seeding():
    actions = sr.plan(FIXTURE)
    creates = [a for a in actions if a["action"] == "dashboard_create"]
    assert len(creates) == 1, "no swarm-dashboard issue in the fixture -> create one"
    body = creates[0]["body"]
    assert "# Swarm Dashboard" in body and "| #1 |" in body and "| #4 |" in body
    state = json.loads(json.dumps(FIXTURE))
    state["issues"].append({"number": 99, "labels": [sr.DASHBOARD_LABEL],
                            "title": sr.DASHBOARD_TITLE, "body": body, "comments": []})
    again = sr.plan(state)
    assert _seed_actions(again) == [1, 4], "the dashboard issue is never seeded"
    assert not [a for a in again if a["action"].startswith("dashboard")], \
        "an up-to-date board re-plans to NO dashboard action (timestamp ignored)"


def test_dashboard_updates_only_on_content_change():
    state = json.loads(json.dumps(FIXTURE))
    state["issues"].append({"number": 99, "labels": [sr.DASHBOARD_LABEL],
                            "title": sr.DASHBOARD_TITLE, "body": "stale", "comments": []})
    actions = [a for a in sr.plan(state) if a["action"] == "dashboard_update"]
    assert len(actions) == 1 and actions[0]["issue"] == 99
    assert "| #4 |" in actions[0]["body"]


def test_dashboard_radar_shows_overlapping_in_progress_paths():
    state = {"latest_release": "v9.9.9", "issues": [
        {"number": 50, "title": "A", "labels": ["in-progress", "agent:ax"],
         "body": "### Files/areas touched\n\nsrc/x.py\nsrc/shared.py", "comments": []},
        {"number": 51, "title": "B", "labels": ["in-progress", "agent:bx"],
         "body": "### Files/areas touched\n\nsrc/shared.py", "comments": []},
    ]}
    body = sr.render_dashboard(state)
    assert "#50 ↔ #51" in body and "`src/shared.py`" in body
    assert "v9.9.9" in body, "the latest release belongs on the board"


def test_plan_dedupes_marker_family_keeping_lowest():
    actions = sr.plan(FIXTURE)
    deletes = sorted(a["comment"] for a in actions if a["action"] == "delete_comment")
    assert deletes == [22, 44], "lowest marker comment (11) and humans (33) survive"


def test_dry_run_logs_but_never_mutates(capsys):
    calls = []
    sr.GH_RUNNER = lambda args: calls.append(args) or (True, "")
    try:
        applied = sr.apply(sr.plan(FIXTURE), "o/r", dry_run=True)
    finally:
        sr.GH_RUNNER = None
    out = capsys.readouterr().out
    assert applied == 0 and calls == [], "dry-run must not touch gh"
    lines = [json.loads(line) for line in out.strip().splitlines()]
    assert all(line["dry_run"] for line in lines) and len(lines) == 5  # +dashboard_create


def test_apply_converges_to_no_op():
    """Idempotency: execute the plan against a mutable copy of the state,
    then re-plan — the second pass must be empty."""
    state = json.loads(json.dumps(FIXTURE))

    def fake_gh(args):
        if args[:2] == ["issue", "edit"] and "--add-label" in args:
            n = int(args[2])
            label = args[args.index("--add-label") + 1]
            for iss in state["issues"]:
                if iss["number"] == n and label not in iss["labels"]:
                    iss["labels"].append(label)
            return True, ""
        if args[:2] == ["issue", "edit"] and "--body" in args:
            n = int(args[2])
            for iss in state["issues"]:
                if iss["number"] == n:
                    iss["body"] = args[args.index("--body") + 1]
            return True, ""
        if args[:2] == ["issue", "create"]:
            state["issues"].append({
                "number": 99, "title": sr.DASHBOARD_TITLE,
                "labels": [sr.DASHBOARD_LABEL],
                "body": args[args.index("--body") + 1], "comments": []})
            return True, "https://github.com/o/r/issues/99"
        if args[:2] in (["issue", "pin"], ["label", "create"]):
            return True, ""
        if args[:1] == ["api"] and "-X" in args and "DELETE" in args:
            cid = int(args[-1].rsplit("/", 1)[-1])
            for iss in state["issues"]:
                iss["comments"] = [c for c in iss["comments"] if c["id"] != cid]
            return True, ""
        return False, "unhandled: %s" % args[:3]

    sr.GH_RUNNER = fake_gh
    try:
        first = sr.plan(state)
        applied = sr.apply(first, "o/r")
        second = sr.plan(state)
    finally:
        sr.GH_RUNNER = None
    assert applied == len(first) == 5          # 2 seeds + 2 deletes + dashboard_create
    assert second == [], "a reconciled state must re-plan to ZERO actions"


def test_seed_creates_missing_label_then_retries():
    calls = []
    state = {"issues": [{"number": 9, "labels": [], "comments": []}]}

    def flaky_gh(args):
        calls.append(args)
        if args[:2] == ["issue", "edit"]:
            # first edit fails (label missing), succeeds after label create
            edits = [c for c in calls if c[:2] == ["issue", "edit"]]
            return (False, "label not found") if len(edits) == 1 else (True, "")
        if args[:2] == ["label", "create"]:
            return True, ""
        return False, "unhandled"

    sr.GH_RUNNER = flaky_gh
    try:
        applied = sr.apply(sr.plan(state), "o/r")
    finally:
        sr.GH_RUNNER = None
    assert applied == 1
    assert any(c[:2] == ["label", "create"] for c in calls), \
        "a fresh repo must get the label created on demand"

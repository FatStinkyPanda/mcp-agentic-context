"""
Collab E2E: the per-commit gate.
================================
Wires the engine selftest and the multi-process swarm harness into pytest so
EVERY commit (pre-push hook) and every push/PR (CI) proves the invariants that
make 100 concurrent agents safe. The heavy knobs come from env:
  SWARM_AGENTS / SWARM_ITERS  (defaults 8 / 25; CI sets 16)
"""

from pathlib import Path
import os
import subprocess
import sys

import pytest

from scripts import agent_collab, agent_comms
from scripts import collab_swarm

AGENTS = int(os.environ.get("SWARM_AGENTS", "8"))
ITERS = int(os.environ.get("SWARM_ITERS", "25"))


def test_env_read_at_call_time(monkeypatch, tmp_path):
    """The isolation contract every test here depends on: MCP_NSYNC_PATH is
    read at CALL time, never cached at import."""
    monkeypatch.setenv("MCP_NSYNC_PATH", str(tmp_path / "one"))
    first = agent_comms.get_nsync_path()
    monkeypatch.setenv("MCP_NSYNC_PATH", str(tmp_path / "two"))
    second = agent_comms.get_nsync_path()
    assert first != second, "get_nsync_path must re-read the env on every call"


def test_collab_health_detects_and_heals(collab_store):
    """The Doctor's collab dimension: collab_health() detects orphaned claims,
    stale leases, corrupt files and stray artifacts; collab_heal() reaps the
    reclaimable ones and keeps live state — the hand-cleanup of a 100-agent
    fleet, made one command."""
    import os
    import time as _t
    from scripts import agent_collab as ac
    P = "doctor-probe"
    now = ac._now()

    ac.claim_add(P, "fresh-area", "a/*", "liveagent")          # must SURVIVE
    ac.claim_add(P, "issue-77", "b/*", "ghost")                # orphan: dead owner, old
    cp = ac._claim_path(P, "issue-77")
    cd = ac._read_json(cp)
    cd["time"] = now - 3600
    ac.atomic_write_json(cp, cd)
    ac.lease_acquire(P, "rusty", "ghost", ttl=0.3)             # stale lease
    _t.sleep(0.5)
    old = now - 2 * 3600                                        # past every GC threshold
    ac.lease_path(P, "broken").write_text("{not json", encoding="utf-8")   # corrupt
    os.utime(ac.lease_path(P, "broken"), (old, old))
    stray = ac.collab_dir(P) / ".probe.json.9.tmp"            # leftover artifact
    stray.write_text("x", encoding="utf-8")
    os.utime(stray, (old, old))

    h = ac.collab_health(P)
    assert h["status"] in ("warn", "error"), h
    assert "issue-77" in h["orphan_claims"]
    assert any(le["resource"] == "rusty" for le in h["stale_leases"])
    assert h["corrupt_files"] and h["stray_artifacts"] >= 1

    counts = ac.collab_heal(P, "doctorbot")
    assert counts, "heal should reap something"
    h2 = ac.collab_health(P)
    assert "issue-77" not in h2["orphan_claims"], "orphan claim must be reaped"
    assert not h2["corrupt_files"], "corrupt file must be cleared"
    assert h2["stray_artifacts"] == 0, "stray artifacts must be cleared"
    assert any(c["id"] == "fresh-area" for c in ac.claims_all(P)), "live claim must survive"


def test_work_next_critical_path(collab_store):
    """work next drains the critical path: within a priority tier, a bottleneck
    that unblocks downstream work outranks a non-bottleneck; priority still
    wins across tiers; blocked issues stay excluded."""
    import json as _json
    import re as _re
    from scripts import agent_collab as ac
    P = "cp-probe"
    issues = [
        {"number": 105, "title": "urgent", "labels": [{"name": "state:available"}],
         "body": "### Priority\n\nP0"},                              # P0 -> first
        {"number": 100, "title": "bottleneck", "labels": [{"name": "state:available"}],
         "body": "### Files/areas touched\n\nsrc/a.py\n\n### Priority\n\nP2"},  # unblocks 3
        {"number": 104, "title": "regular", "labels": [{"name": "state:available"}],
         "body": "### Files/areas touched\n\nsrc/b.py\n\n### Priority\n\nP2"},   # unblocks 0
        {"number": 101, "title": "d1", "labels": [{"name": "state:available"}],
         "body": "### Blocked by\n\n#100\n\n### Priority\n\nP2"},
        {"number": 102, "title": "d2", "labels": [{"name": "state:available"}],
         "body": "### Blocked by\n\n#100\n\n### Priority\n\nP2"},
        {"number": 103, "title": "d3", "labels": [{"name": "state:available"}],
         "body": "### Blocked by\n\n#100\n\n### Priority\n\nP2"},
    ]

    def fake(args):
        if args[:2] == ["issue", "list"]:
            return True, _json.dumps(issues)
        return False, "unhandled %s" % args[:3]

    ok, msg = ac.work_next(P, "agentX", runner=fake)
    assert ok, msg
    order = [int(x) for x in _re.findall(r"#(\d+)", msg)]
    assert order[:3] == [105, 100, 104], \
        "P0 first, then the P2 bottleneck before the P2 regular: %s" % order
    assert "unblocks=3" in msg, "the bottleneck's unblock count is shown"
    assert not ({101, 102, 103} & set(order)), "blocked issues are excluded"


def test_collab_metrics(collab_store):
    """Fleet analytics from the journal: throughput, cycle time (start->land
    paired by issue), contention, and windowing (old events excluded)."""
    import json as _json
    import time as _time
    from scripts import agent_collab as ac
    P = "metrics-probe"
    base = ac.collab_dir(P)
    now = ac._now()

    def ev(dt, who, event, data):
        t = now - dt
        return _json.dumps({"t": t, "ts": _time.ctime(t), "who": who,
                            "event": event, "data": data})

    (base / "journal.ndjson").write_text("\n".join([   # write-ok: test fixture
        ev(3600, "a", "work.start", {"issue": 1}),
        ev(3000, "a", "work.landed", {"issue": 1, "pr": 10}),     # cycle 10 min
        ev(1800, "b", "work.start", {"issue": 2}),
        ev(900,  "b", "work.done",  {"issue": 2}),                # cycle 15 min
        ev(1200, "c", "work.start", {"issue": 3}),                # in-flight
        ev(1000, "c", "work.lost_race", {"issue": 4}),
        ev(500,  "d", "lease.acquired", {"resource": "x"}),
        ev(400,  "d", "lease.broke_stale", {"resource": "x"}),
        ev(300,  "e", "identity.collision", {}),
        ev(90000, "old", "work.start", {"issue": 99}),            # 25h ago -> excluded
    ]) + "\n", encoding="utf-8")

    m = ac.collab_metrics(P, hours=24.0)
    assert m["work"]["started"] == 3, "the 25h-old start is outside the window"
    assert m["work"]["completed"] == 2
    assert m["work"]["in_flight"] == 1
    assert m["work"]["lost_race"] == 1
    assert m["cycle_time"]["completed"] == 2
    assert 12 <= m["cycle_time"]["mean_minutes"] <= 13       # mean of 10 and 15
    assert m["leases"]["acquired"] == 1 and m["leases"]["broke_stale"] == 1
    assert m["contention"]["collisions"] == 1 and m["contention"]["lost_races"] == 1
    assert m["by_event"]["work.start"] == 3
    assert {a["agent"] for a in m["top_agents"]} >= {"a", "b", "c", "d", "e"}


def test_issue_form_template_matches_parser():
    """The CONTRACT pin: every parser field label appears verbatim as a form
    label in .github/ISSUE_TEMPLATE/agent-task.yml, and the template seeds
    state:available — drifting either side silently degrades path extraction."""
    template = (Path(agent_collab.__file__).resolve().parents[2]
                / ".github" / "ISSUE_TEMPLATE" / "agent-task.yml")
    text = template.read_text(encoding="utf-8")
    assert "state:available" in text, "template must seed the claimable state label"
    for label in agent_collab.FORM_FIELDS.values():
        assert ("label: %s" % label) in text, (
            "FORM_FIELDS label %r is missing from agent-task.yml — "
            "the parser and the template must change together" % label)


def test_selftest_green(collab_store):
    """Parity pin: the CLI selftest and pytest agree forever."""
    ok, lines = agent_collab.selftest()
    assert ok, "selftest failed:\n" + "\n".join(
        line for line in lines if not line.startswith("PASS"))


def test_selftest_cli_exit_contract(collab_store):
    """Exit-code + final-line contract of `collab selftest` (direct script
    invocation — no venv bootstrap in CI)."""
    script = Path(agent_collab.__file__).resolve()
    proc = subprocess.run([sys.executable, "-X", "utf8", str(script), "selftest"],
                          capture_output=True, text=True, timeout=600,
                          encoding="utf-8", errors="replace",
                          cwd=str(script.parents[1]))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "COLLAB_ENGINE_OK" in proc.stdout


def _assert_swarm(report):
    failed = [c for c in report["checks"] if not c["ok"]]
    assert report["ok"], "swarm failures (store kept at %s):\n%s" % (
        report["store"],
        "\n".join("%s  [%s]" % (c["name"], c.get("detail", "")) for c in failed))


def test_swarm_parallelism_is_bounded():
    """A verification harness must never be able to fork-bomb the host: the
    safe cap is CPU-bounded and >= 2, and an explicit cap is honored."""
    import os
    cpu = os.cpu_count() or 4
    for n in (1, 8, 100, 1000):
        cap = collab_swarm._safe_parallel(n)
        assert 2 <= cap <= max(2, cpu), "cap %d out of bounds for %d agents" % (cap, n)
        assert cap <= n or n < 2, "cap must not exceed agent count"


@pytest.mark.swarm
def test_swarm_pool_runs_all_identities_under_cap():
    """All agents run even though only max_parallel are ever live at once,
    and every invariant still holds (bounded contention is valid contention)."""
    report = collab_swarm.run_swarm(agents=8, iters=8, hammer=True,
                                    max_parallel=3, timeout=120)
    _assert_swarm(report)
    assert report["parallel"] == 3


@pytest.mark.swarm
def test_swarm_store_primitives():
    """N processes: lease mutual exclusion, journal exactly-once, claim CAS."""
    _assert_swarm(collab_swarm.run_swarm(
        agents=AGENTS, iters=ITERS, roles=("mutex", "journal", "claim"), timeout=240))


@pytest.mark.swarm
def test_swarm_hammer_fencing():
    """Forced lease expiry mid-critical-section: zombies must observe the lost
    fence and never write (the Kleppmann fencing property, empirically)."""
    _assert_swarm(collab_swarm.run_swarm(
        agents=AGENTS, iters=max(10, ITERS // 2), roles=("mutex",),
        hammer=True, timeout=240))


@pytest.mark.swarm
def test_swarm_checkout_and_collision():
    """Issue checkout single-winner across processes + same-identity detection."""
    _assert_swarm(collab_swarm.run_swarm(
        agents=AGENTS, iters=ITERS, roles=("checkout", "collide"), timeout=240))


@pytest.mark.swarm
def test_swarmtest_cli_exit_contract():
    """Exit-code + final-line contract of `collab swarmtest`."""
    script = Path(collab_swarm.__file__).resolve()
    proc = subprocess.run([sys.executable, "-X", "utf8", str(script), "run",
                           "--agents", "4", "--iters", "8"],
                          capture_output=True, text=True, timeout=600,
                          encoding="utf-8", errors="replace",
                          cwd=str(script.parents[1]))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "COLLAB_SWARM_OK" in proc.stdout


@pytest.mark.soak
def test_soak_100_agents():
    """The headline claim: 100 distinct agent identities contending one store
    under hammer-mode lease churn, with at most max_parallel live processes so
    the harness never saturates the host. Nightly CI; ~15-30 minutes."""
    _assert_swarm(collab_swarm.run_swarm(
        agents=100, iters=40, hammer=True, timeout=1800, max_parallel=16))

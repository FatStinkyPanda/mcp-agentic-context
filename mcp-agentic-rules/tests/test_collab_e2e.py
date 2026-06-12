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
    """The headline claim, literally: 100 concurrent agent processes on one
    store with hammer-mode lease churn. Nightly CI; ~15-30 minutes (the mutex
    role serializes 4000 critical sections on 2-core runners)."""
    _assert_swarm(collab_swarm.run_swarm(
        agents=100, iters=40, hammer=True, timeout=1800))

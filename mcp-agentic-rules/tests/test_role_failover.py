"""Cross-device ROLE leadership: single-active + automatic failover (the multi-device keystone).

Proves that a ROLE (e.g. "maestro") is a fleet-wide singleton — exactly ONE instance is ACTIVE across all
devices — and that leadership fails over to a standby when the active instance's device goes offline,
fence-protected against split-brain. Built on the fenced lease, so these tests also guard that the role
layer inherits the lease's monotonic-fence and stale-break guarantees.
"""
import time

from scripts import agent_collab as ac


def _isolate(monkeypatch, tmp_path, name):
    # MCP_NSYNC_PATH is read at call time (the isolation contract) — point the collab store at a tmp dir.
    monkeypatch.setenv("MCP_NSYNC_PATH", str(tmp_path / name))


def test_role_single_active_failover_and_fencing(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, "role")
    P = "role-probe"

    # 1. the first instance becomes ACTIVE
    active_a, info_a = ac.role_acquire(P, "maestro", "maestro@A", ttl=0.4)
    assert active_a is True
    f1 = int(info_a["fence"])

    # 2. a second instance (a DIFFERENT device) is a hot STANDBY while A is live — it does NOT become active
    active_b, info_b = ac.role_acquire(P, "maestro", "maestro@B", ttl=0.4)
    assert active_b is False
    assert info_b["owner"] == "maestro@A"

    # 3. A's device goes offline -> its lease goes stale -> B's next acquire TAKES OVER with a HIGHER fence
    time.sleep(0.6)
    active_b2, info_b2 = ac.role_acquire(P, "maestro", "maestro@B", ttl=5.0)
    assert active_b2 is True
    f2 = int(info_b2["fence"])
    assert f2 > f1, "failover must mint a strictly higher fence (no split-brain on a resurrected holder)"

    # 4. A returns -> it is now the STANDBY (B holds it live)
    active_a2, info_a2 = ac.role_acquire(P, "maestro", "maestro@A", ttl=5.0)
    assert active_a2 is False
    assert info_a2["owner"] == "maestro@B"

    # 5. graceful step-down (release) -> a standby takes over IMMEDIATELY, not after the TTL
    ok, _ = ac.role_release(P, "maestro", "maestro@B", f2)
    assert ok is True
    active_a3, info_a3 = ac.role_acquire(P, "maestro", "maestro@A", ttl=5.0)
    assert active_a3 is True
    assert int(info_a3["fence"]) > f2

    # role_holder reflects the live truth
    h = ac.role_holder(P, "maestro")
    assert h and h["owner"] == "maestro@A" and not h["stale"]


def test_role_grace_defers_recovering_primary(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, "grace")
    P = "role-grace-probe"

    ac.role_acquire(P, "planner", "planner@primary", ttl=0.4)
    time.sleep(0.6)  # the primary's lease has just gone stale

    # a standby WITH a grace window DEFERS — it lets the briefly-offline primary recover (no flap)
    active, info = ac.role_acquire(P, "planner", "planner@standby", ttl=5.0, grace=60.0)
    assert active is False
    assert info.get("deferring")

    # WITHOUT a grace window (grace=0, the primary's own default), it takes over immediately
    active2, _ = ac.role_acquire(P, "planner", "planner@standby", ttl=5.0, grace=0.0)
    assert active2 is True


def test_roles_all_lists_active_roles(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, "all")
    P = "roles-all-probe"
    ac.role_acquire(P, "maestro", "maestro@A", ttl=5.0)
    ac.role_acquire(P, "scout", "scout@B", ttl=5.0)
    roles = ac.roles_all(P)
    assert set(roles) == {"maestro", "scout"}
    assert roles["maestro"]["owner"] == "maestro@A"


def test_fleet_pause_resume(monkeypatch, tmp_path):
    """The fleet-wide kill-switch the owner flips from Telegram/CLI: a synced marker that every agent loop
    checks. Pause sets it (with who/reason); resume clears it; status reads it; resume-when-not-paused is a
    no-op. (Loops idle while fleet_paused() is truthy — verified by the loop wiring, not here.)"""
    _isolate(monkeypatch, tmp_path, "pause")
    P = "fleet-pause-probe"
    assert ac.fleet_paused(P) is None                  # running by default
    ac.fleet_pause(P, "owner", "maintenance")
    p = ac.fleet_paused(P)
    assert p and p["paused"] is True and p["by"] == "owner" and p["reason"] == "maintenance"
    assert ac.fleet_resume(P, "owner") is True          # was paused -> resumed
    assert ac.fleet_paused(P) is None
    assert ac.fleet_resume(P, "owner") is False         # resume when not paused = no-op

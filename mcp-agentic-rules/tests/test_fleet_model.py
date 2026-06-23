"""Fleet MODEL switch: the owner picks which model (+ reasoning effort) each agent runs — per-agent OR
fleet-wide — from anywhere (Telegram/CLI). It is a synced config every agent loop re-reads at the top of
each tick. These prove the resolution order (per-agent override > fleet default > unset), that an 'all'
switch is an authoritative reset (clears overrides), alias/effort normalization, and that an unknown model
fails CLOSED (raises, writes nothing — so a typo can never crash-loop a headless tick)."""
import pytest

from scripts import agent_collab as ac


def _isolate(monkeypatch, tmp_path, name):
    # MCP_NSYNC_PATH is read at call time (the isolation contract) — point the collab store at a tmp dir.
    monkeypatch.setenv("MCP_NSYNC_PATH", str(tmp_path / name))


def test_fleet_model_set_get_all_and_override(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, "model")
    P = "fleet-model-probe"

    # unset -> ('', '') so each loop keeps its own env default
    assert ac.fleet_model_get(P, "scout") == ("", "")

    # 'all' sets the fleet default for EVERY agent (friendly alias + 'max' effort both normalize)
    e = ac.fleet_model_set(P, "owner", "all", "sonnet", "max")
    assert e == {"target": "all", "model": "claude-sonnet-4-6", "effort": "high"}
    assert ac.fleet_model_get(P, "scout") == ("claude-sonnet-4-6", "high")
    assert ac.fleet_model_get(P, "aether") == ("claude-sonnet-4-6", "high")

    # a per-agent override beats the default for that agent ONLY; its unset effort falls through to default
    ac.fleet_model_set(P, "owner", "aether", "opus")
    assert ac.fleet_model_get(P, "aether") == ("claude-opus-4-8", "high")
    assert ac.fleet_model_get(P, "scout") == ("claude-sonnet-4-6", "high")

    # 'all' again is an AUTHORITATIVE reset — it clears every per-agent override
    ac.fleet_model_set(P, "owner", "all", "opus", "high")
    assert ac.fleet_model_get(P, "aether") == ("claude-opus-4-8", "high")
    assert (ac.fleet_model_all(P).get("overrides") or {}) == {}


def test_fleet_model_normalization_and_fail_closed(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, "model2")
    P = "fleet-model-norm"

    assert ac.normalize_model("Sonnet") == "claude-sonnet-4-6"          # friendly alias, case-insensitive
    assert ac.normalize_model("claude-opus-5-0") == "claude-opus-5-0"   # canonical id passes through (future models)
    assert ac.normalize_effort("MAX") == "high"                         # 'max' -> the Claude.ai ceiling
    assert ac.normalize_effort("") == ""                                # unset stays unset

    # an unknown bare model fails CLOSED: raises, writes nothing (no partial config a loop could read)
    with pytest.raises(ValueError):
        ac.fleet_model_set(P, "owner", "all", "gpt-9")
    assert ac.fleet_model_all(P) == {"default": {}, "overrides": {}}

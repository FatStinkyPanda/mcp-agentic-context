#!/usr/bin/env python3
"""
MCP Agent Collaboration: LEASES + CLAIMS + JOURNAL
==================================================
The coordination primitives that let MULTIPLE agent sessions work on the SAME project at the
same time without stepping on each other:

  LEASES   exclusive, TTL'd locks on contended resources (an editor, a build pipeline, the
           git-commit window). Atomic acquire (O_EXCL create), owner-renewed, auto-breakable
           once stale — a crashed session can never deadlock the team.
  CLAIMS   advisory ownership of work areas ("I'm editing src/creatures/*") so two agents
           don't author conflicting changes.
  JOURNAL  an append-only per-project event log — the team's radio channel. Every agent logs
           what it does (commits, rebuilds, results, intents) and tails it to know what
           everyone else is doing.

Store layout (shared with agent_comms presence/mailboxes; NSync propagates cross-machine):
  ~/.mcp/nsync/.nsync_agents/collab/<project>/leases/<resource>.json
  ~/.mcp/nsync/.nsync_agents/collab/<project>/claims/<id>.json
  ~/.mcp/nsync/.nsync_agents/collab/<project>/journal.ndjson

This file format IS the contract: thin per-project clients (e.g. AI_Gen's scripts/collab.py)
may read/write the same files directly with stdlib only.

Usage: mcp collab <command> [args] [--project P] [--as IDENTITY]
  lease acquire <resource> [--ttl SECONDS] [--note TEXT] [--wait SECONDS]
  lease release <resource>
  lease renew   <resource>
  lease status  [resource]
  lease break   <resource>            (only succeeds if the lease is STALE)
  claim add <id> <pattern> [--note TEXT]
  claim drop <id>
  claim list
  journal log <event> [--data JSON]
  journal tail [N]
  status                              (presence + leases + claims + journal tail, one view)
  heartbeat [STATUS] [TASK]           (presence beat — also detects identity collisions)
  onboard                             (print the complete join-the-team procedure for an agent)
  selftest                            (verify the whole engine on an isolated scope — 6 checks)
  whoami

IDENTITY RULE: one working directory = one agent identity. If two sessions in DIFFERENT
directories heartbeat the same identity, status/heartbeat warn loudly (identity collision —
leases cannot protect sessions that look like one agent). Give each session its own checkout
(e.g. `git worktree add`) and its own call-sign.
"""

from pathlib import Path
import json
import os
import sys
import time

try:
    from scripts.agent_comms import get_comms_dir, get_hostname, AgentPresence
except ImportError:  # direct invocation outside the package
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.agent_comms import get_comms_dir, get_hostname, AgentPresence

DEFAULT_TTL = 600.0   # 10 minutes — heartbeat-renewed leases never expire while their owner lives


# ── store ─────────────────────────────────────────────────────────────────────────────────────
def collab_dir(project: str) -> Path:
    d = get_comms_dir() / "collab" / project
    (d / "leases").mkdir(parents=True, exist_ok=True)
    (d / "claims").mkdir(parents=True, exist_ok=True)
    return d


def identity() -> str:
    return os.environ.get("AGENT_IDENTITY") or get_hostname()


def _now() -> float:
    return time.time()


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── presence + identity-collision detection ──────────────────────────────────────────────────
def heartbeat(who: str, status: str = "active", task: str = "", project: str = "default"):
    """Presence beat carrying the WORKDIR. Returns (payload, collision_warning_or_None).
    Two live sessions beating one identity from DIFFERENT workdirs = an identity collision:
    leases cannot protect sessions that look like one agent."""
    presence_file = get_comms_dir() / f"{who}.json"
    warning = None
    prev = None
    try:
        prev = json.loads(presence_file.read_text(encoding="utf-8"))
    except Exception:
        pass
    cwd = str(Path.cwd())
    if prev and prev.get("workdir") and prev["workdir"] != cwd \
            and (_now() - prev.get("timestamp", 0)) < 300:
        warning = ("IDENTITY COLLISION: '%s' heartbeated from '%s' %ds ago and is now beating "
                   "from '%s'. Two sessions are sharing one identity — leases CANNOT protect "
                   "them from each other. Give this session its own checkout (git worktree) and "
                   "call-sign." % (who, prev["workdir"], int(_now() - prev.get("timestamp", 0)), cwd))
        journal_log(project, who, "identity.collision",
                    {"previous_workdir": prev["workdir"], "current_workdir": cwd})
    payload = {"hostname": who, "timestamp": _now(), "status": status,
               "current_task": task, "last_seen": time.ctime(), "workdir": cwd}
    presence_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload, warning


# ── leases ────────────────────────────────────────────────────────────────────────────────────
def lease_path(project: str, resource: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in resource)
    return collab_dir(project) / "leases" / f"{safe}.json"


def lease_info(project: str, resource: str):
    """Current lease dict or None. Adds derived 'stale' and 'expires_in'."""
    data = _read_json(lease_path(project, resource))
    if not data:
        return None
    age = _now() - float(data.get("renewed", data.get("acquired", 0)))
    data["expires_in"] = float(data.get("ttl", DEFAULT_TTL)) - age
    data["stale"] = data["expires_in"] <= 0
    return data


def lease_acquire(project: str, resource: str, who: str, ttl: float = DEFAULT_TTL, note: str = ""):
    """Atomically acquire (or re-enter/renew when already the owner; auto-break when stale).
    Returns (ok, lease_dict_or_holder)."""
    path = lease_path(project, resource)
    for _ in range(3):
        current = lease_info(project, resource)
        if current:
            if current.get("owner") == who:
                return lease_renew(project, resource, who)        # re-entrant
            if not current["stale"]:
                return False, current                              # held by a LIVE other
            try:                                                   # stale → break + retry
                path.unlink()
                journal_log(project, who, "lease.broke_stale",
                            {"resource": resource, "previous_owner": current.get("owner")})
            except FileNotFoundError:
                pass
        payload = {"resource": resource, "owner": who, "acquired": _now(),
                   "renewed": _now(), "ttl": ttl, "note": note}
        try:
            with open(path, "x", encoding="utf-8") as f:           # O_EXCL: atomic on NTFS/POSIX
                json.dump(payload, f, indent=2)
            journal_log(project, who, "lease.acquired", {"resource": resource, "note": note})
            return True, payload
        except FileExistsError:
            continue                                               # lost the race — re-evaluate
    return False, lease_info(project, resource)


def lease_renew(project: str, resource: str, who: str):
    path = lease_path(project, resource)
    current = lease_info(project, resource)
    if not current or current.get("owner") != who:
        return False, current
    current["renewed"] = _now()
    current.pop("expires_in", None)
    current.pop("stale", None)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return True, current


def lease_release(project: str, resource: str, who: str):
    path = lease_path(project, resource)
    current = lease_info(project, resource)
    if not current:
        return True, None
    if current.get("owner") != who and not current["stale"]:
        return False, current
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    journal_log(project, who, "lease.released", {"resource": resource})
    return True, None


def lease_break(project: str, resource: str, who: str):
    """Break ONLY a stale lease (a live owner's lease cannot be stolen)."""
    current = lease_info(project, resource)
    if not current:
        return True, None
    if not current["stale"]:
        return False, current
    try:
        lease_path(project, resource).unlink()
    except FileNotFoundError:
        pass
    journal_log(project, who, "lease.broke_stale",
                {"resource": resource, "previous_owner": current.get("owner")})
    return True, None


def leases_all(project: str):
    out = {}
    for f in (collab_dir(project) / "leases").glob("*.json"):
        data = lease_info(project, f.stem)
        if data:
            out[data.get("resource", f.stem)] = data
    return out


# ── claims (advisory work-area ownership) ─────────────────────────────────────────────────────
def claim_add(project: str, claim_id: str, pattern: str, who: str, note: str = ""):
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in claim_id)
    path = collab_dir(project) / "claims" / f"{safe}.json"
    existing = _read_json(path)
    if existing and existing.get("owner") != who:
        return False, existing
    payload = {"id": claim_id, "pattern": pattern, "owner": who, "note": note, "time": _now()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    journal_log(project, who, "claim.added", {"id": claim_id, "pattern": pattern, "note": note})
    return True, payload


def claim_drop(project: str, claim_id: str, who: str):
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in claim_id)
    path = collab_dir(project) / "claims" / f"{safe}.json"
    existing = _read_json(path)
    if existing and existing.get("owner") not in (who, None):
        age_h = (_now() - existing.get("time", 0)) / 3600.0
        if age_h < 24:                                              # stale claims (24h) droppable by anyone
            return False, existing
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    journal_log(project, who, "claim.dropped", {"id": claim_id})
    return True, None


def claims_all(project: str):
    return [c for f in (collab_dir(project) / "claims").glob("*.json")
            if (c := _read_json(f))]


# ── journal (the team's radio channel) ────────────────────────────────────────────────────────
JOURNAL_ROTATE_BYTES = 2 * 1024 * 1024   # rotate at 2 MB so the radio channel never bloats


def journal_log(project: str, who: str, event: str, data=None):
    path = collab_dir(project) / "journal.ndjson"
    try:
        if path.exists() and path.stat().st_size > JOURNAL_ROTATE_BYTES:
            rotated = path.with_name("journal.1.ndjson")
            rotated.unlink(missing_ok=True)
            path.rename(rotated)
    except OSError:
        pass   # rotation is best-effort; never lose the event over it
    line = json.dumps({"t": _now(), "ts": time.ctime(), "who": who,
                       "event": event, "data": data or {}}, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def journal_tail(project: str, n: int = 20):
    path = collab_dir(project) / "journal.ndjson"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for raw in lines[-n:]:
        try:
            out.append(json.loads(raw))
        except Exception:
            pass
    return out


# ── onboarding (the "you are an additional agent" answer, generic for any project) ────────────
ONBOARD_TEXT = """\
=== HOW TO JOIN A MULTI-AGENT COLLAB TEAM (mcp collab) ===
You were told you're an ADDITIONAL AGENT on a team. Do exactly this:

0. IDENTITY RULE — one working directory = one agent. Run `mcp collab status --project <P>`:
   if an ACTIVE agent already heartbeats from THIS directory, STOP — this directory is that
   agent's seat. Get your own checkout (`git worktree add ../<proj>_<callsign>`) first.
1. Pick a CALL-SIGN and use it on every command via --as <callsign> (or set AGENT_IDENTITY).
   Heartbeat yourself in: `mcp collab heartbeat active "joining the team" --as <callsign>`.
2. READ THE ROOM: `mcp collab status --project <P>` — active agents + their tasks, every
   lease (who is allowed to do what), claims (who owns which source areas), the journal tail
   (what just happened). Check your mail: `mcp comms listen`.
3. THE LEASE LAW (typical resources — projects may define more):
   - A lease is EXCLUSIVE while its holder is alive (TTL-renewed). NEVER work around a held
     lease; coordinate via messages/journal instead. Stale leases auto-break — never deadlock.
   - Common leases: a live tool/editor seat (its holder is the PILOT), build/rebuild rights,
     the git-commit window (hold while rebase+push), exclusive test/bench windows.
4. CLAIM before you author: `mcp collab claim add <id> "<path-pattern>" --as <callsign>` —
   and respect existing claims shown in status.
5. JOURNAL everything material: intents before, results after —
   `mcp collab journal log intent --data '{"text": "..."}'`. Tail it at EVERY loop start.
6. LANDING WORK: acquire the git-commit lease -> fetch + rebase -> push -> release -> journal
   the commit hash.
7. Message any teammate: `mcp comms send <callsign> note "<text>"`; read yours each loop.
Projects may carry their own onboarding (e.g. a repo skill) with project-specific lease names —
that version wins on specifics.
"""


def selftest():
    """Verify the engine end-to-end on an isolated scope. Returns (ok, lines)."""
    import shutil
    P = "collab-selftest"
    lines = []
    ok = True

    def check(name, cond):
        nonlocal ok
        lines.append(("PASS " if cond else "FAIL ") + name)
        ok = ok and cond

    shutil.rmtree(get_comms_dir() / "collab" / P, ignore_errors=True)
    a_ok, _ = lease_acquire(P, "seat", "selfA", ttl=600)
    b_ok, b_info = lease_acquire(P, "seat", "selfB", ttl=600)
    a_again, _ = lease_acquire(P, "seat", "selfA", ttl=600)
    rel_b, _ = lease_release(P, "seat", "selfB")
    check("lease exclusion + re-entrancy + foreign-release refusal",
          a_ok and not b_ok and b_info.get("owner") == "selfA" and a_again and not rel_b)
    lease_release(P, "seat", "selfA")
    lease_acquire(P, "seat", "selfA", ttl=0.5)
    time.sleep(0.8)
    b2_ok, _ = lease_acquire(P, "seat", "selfB", ttl=600)
    check("stale lease auto-break", b2_ok and lease_info(P, "seat")["owner"] == "selfB")
    lease_release(P, "seat", "selfB")
    journal_log(P, "selfA", "t.one", {"n": 1})
    journal_log(P, "selfB", "t.two", {"n": 2})
    tail = journal_tail(P, 50)
    evs = [(e["who"], e["event"]) for e in tail]
    check("journal order", ("selfA", "t.one") in evs and ("selfB", "t.two") in evs
          and evs.index(("selfA", "t.one")) < evs.index(("selfB", "t.two")))
    c_ok, _ = claim_add(P, "area", "src/*", "selfA")
    c2_ok, c2 = claim_add(P, "area", "src/x", "selfB")
    d_ok, _ = claim_drop(P, "area", "selfA")
    check("claim conflict + drop", c_ok and not c2_ok and c2.get("owner") == "selfA" and d_ok)
    w_ok, w_info = lease_acquire(P, "waitres", "selfA", ttl=0.5)
    t0 = time.time()
    got = False
    while time.time() - t0 < 5.0:                       # --wait semantics, inlined
        okw, _ = lease_acquire(P, "waitres", "selfB", ttl=600)
        if okw:
            got = True
            break
        time.sleep(0.3)
    check("wait-acquire over an expiring lease", got)
    lease_release(P, "waitres", "selfB")
    pay, warn = heartbeat("selfC", "active", "selftest", P)
    check("heartbeat carries workdir", pay.get("workdir") == str(Path.cwd()) and warn is None)
    return ok, lines


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────
def _pop_opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            val = args[i + 1]
            del args[i:i + 2]
            return val
        del args[i]
    return default


def main():
    args = list(sys.argv[1:])
    project = _pop_opt(args, "--project", os.environ.get("MCP_COLLAB_PROJECT", "default"))
    who = _pop_opt(args, "--as", identity())
    note = _pop_opt(args, "--note", "")
    ttl = float(_pop_opt(args, "--ttl", DEFAULT_TTL))
    data_json = _pop_opt(args, "--data", "{}")

    if not args:
        print(__doc__)
        return 0
    cmd = args[0]

    if cmd == "whoami":
        print(who)
        return 0

    if cmd == "onboard":
        print(ONBOARD_TEXT)
        return 0

    if cmd == "selftest":
        ok, lines = selftest()
        for line in lines:
            print(line)
        print("COLLAB_ENGINE_OK" if ok else "COLLAB_ENGINE_FAIL")
        return 0 if ok else 1

    if cmd == "heartbeat":
        status = args[1] if len(args) > 1 else "active"
        task = " ".join(args[2:]) if len(args) > 2 else ""
        _, warn = heartbeat(who, status, task, project)
        print("[OK] heartbeat updated")
        if warn:
            print("[WARN] " + warn)
        return 0

    if cmd == "lease" and len(args) >= 2:
        verb = args[1]
        if verb == "status":
            target = args[2] if len(args) > 2 else None
            entries = {target: lease_info(project, target)} if target else leases_all(project)
            for name, info in sorted(entries.items()):
                if not info:
                    print(f"{name}: FREE")
                else:
                    state = "STALE" if info["stale"] else f"{int(info['expires_in'])}s left"
                    print(f"{info['resource']}: held by {info['owner']} ({state})  note={info.get('note', '')}")
            if not entries:
                print("(no leases)")
            return 0
        if len(args) < 3:
            print("[FAIL] lease %s needs a resource" % verb)
            return 1
        resource = args[2]
        wait_s = float(_pop_opt(args, "--wait", 0) or 0)
        fn = {"acquire": lambda: lease_acquire(project, resource, who, ttl, note),
              "release": lambda: lease_release(project, resource, who),
              "renew": lambda: lease_renew(project, resource, who),
              "break": lambda: lease_break(project, resource, who)}.get(verb)
        if not fn:
            print(f"[FAIL] unknown lease verb: {verb}")
            return 1
        ok, info = fn()
        if not ok and verb == "acquire" and wait_s > 0:
            deadline = time.time() + wait_s
            while not ok and time.time() < deadline:   # poll until the holder releases/expires
                time.sleep(min(2.0, max(0.3, wait_s / 20.0)))
                ok, info = fn()
        if ok:
            print(f"[OK] {verb} {resource} ({who})")
            return 0
        holder = info.get("owner", "?") if info else "?"
        left = int(info.get("expires_in", 0)) if info else 0
        print(f"[HELD] {resource} is held by {holder} ({left}s left) — coordinate via journal/messages")
        return 1

    if cmd == "claim" and len(args) >= 2:
        verb = args[1]
        if verb == "list":
            for c in claims_all(project):
                print(f"{c['id']}: {c['pattern']} (owner {c['owner']})  note={c.get('note', '')}")
            return 0
        if verb == "add" and len(args) >= 4:
            ok, info = claim_add(project, args[2], args[3], who, note)
            print("[OK] claimed" if ok else f"[HELD] claimed by {info.get('owner')}")
            return 0 if ok else 1
        if verb == "drop" and len(args) >= 3:
            ok, info = claim_drop(project, args[2], who)
            print("[OK] dropped" if ok else f"[HELD] owned by {info.get('owner')}")
            return 0 if ok else 1
        print("[FAIL] claim add <id> <pattern> | drop <id> | list")
        return 1

    if cmd == "journal" and len(args) >= 2:
        if args[1] == "log" and len(args) >= 3:
            try:
                payload = json.loads(data_json)
            except Exception:
                payload = {"raw": data_json}
            journal_log(project, who, args[2], payload)
            print("[OK] logged")
            return 0
        if args[1] == "tail":
            n = int(args[2]) if len(args) > 2 else 20
            for e in journal_tail(project, n):
                print(f"{e['ts']}  {e['who']:<18} {e['event']:<22} {json.dumps(e['data'], ensure_ascii=False)[:120]}")
            return 0
        print("[FAIL] journal log <event> [--data JSON] | tail [N]")
        return 1

    if cmd == "status":
        _, warn = heartbeat(who, "active", f"collab status check ({project})", project)
        print(f"=== {project} collaboration status (you are: {who}) ===")
        if warn:
            print("[WARN] " + warn)
        print("\n-- agents (presence) --")
        for f in sorted(get_comms_dir().glob("*.json")):
            d = _read_json(f)
            if not d or "timestamp" not in d:
                continue
            age = _now() - d.get("timestamp", 0)
            mark = "ACTIVE" if age < 120 else "stale"
            wd = d.get("workdir", "?")
            print(f"  {f.stem:<20} [{mark:>6}] {d.get('current_task', '?')[:50]}  ({int(age)}s ago)  @{wd}")
        print("\n-- leases --")
        all_leases = leases_all(project)
        if not all_leases:
            print("  (all free)")
        for name, info in sorted(all_leases.items()):
            state = "STALE" if info["stale"] else f"{int(info['expires_in'])}s left"
            print(f"  {name:<14} held by {info['owner']} ({state})  {info.get('note', '')}")
        print("\n-- claims --")
        cs = claims_all(project)
        if not cs:
            print("  (none)")
        for c in cs:
            print(f"  {c['id']:<20} {c['pattern']}  (owner {c['owner']})")
        print("\n-- journal (last 10) --")
        for e in journal_tail(project, 10):
            print(f"  {e['ts']}  {e['who']:<16} {e['event']:<20} {json.dumps(e['data'], ensure_ascii=False)[:100]}")
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())

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
  join [callsign] [--no-verify]       (take a seat + verify the engine + read the room)
  seat init [callsign]                (bind THIS workdir to a call-sign — one workdir = one agent)
  seat new <callsign>                 (provision a git-worktree seat for another agent on this device)
  seat status                         (identity, where it resolved from, workdir)
  lease acquire <resource> [--ttl SECONDS] [--note TEXT] [--wait SECONDS]   (prints fence=N)
  lease release <resource> [--fence N]
  lease renew   <resource> [--fence N]
  lease valid   <resource> --fence N  (still holding THIS incarnation? exit 0/1)
  lease status  [resource]
  lease break   <resource>            (only succeeds if the lease is STALE or corrupt)
  claim add <id> <pattern> [--note TEXT]
  claim drop <id>
  claim list
  work list                           (open GitHub issues + who has them checked out)
  work start <issue#> [--branch]      (check OUT an issue: assign + label, claim, journal)
  work done <issue#> [--pr URL]       (close it — or link the PR — and release everything)
  work drop <issue#>                  (un-checkout without finishing)
  work tick <issue#> <item#>          (tick task-list checkbox N inside the issue body)
  journal log <event> [--data JSON]
  journal tail [N]
  status                              (presence + leases + claims + work + journal, one view)
  heartbeat [STATUS] [TASK]           (presence beat — also detects identity collisions)
  gc [--dry-run]                      (janitor pass: reap stale presence/claims/records/strays)
  onboard                             (print the complete join-the-team procedure for an agent)
  selftest                            (verify the whole engine inside a throwaway store)
  swarmtest [--agents N] [--iters K] [--hammer] [--keep] [--json]
                                      (N real OS processes prove the multi-agent invariants)
  whoami

WORK = GitHub-native collaboration: an agent's unit of work is a GitHub issue, checked out
like a lease. `work start` assigns the issue, labels it `in-progress` + `agent:<callsign>`,
creates the matching claim (issue URL in its note), records it in the store, and journals
`work.start`. All GitHub access goes through the `gh` CLI and degrades with a clear error
when gh/network is absent — leases/claims/journal never depend on it.

IDENTITY RULE: one working directory = one agent identity, bound by a SEAT file
(.mcp/seat.json, created once via `seat init`/`join`, resolved by identity() ahead of the
hostname fallback). N agents on ONE device each get their own worktree seat (`seat new`).
Cross-workdir use of one identity is REFUSED at the lease/claim/work layer (structural
enforcement), and heartbeats detect collisions (different workdir, or concurrent sessions
in one workdir).

ATOMICITY: every store write is either an O_EXCL create (the CAS for new records), an
atomic temp+rename replace (atomic_write_json — readers never see partial JSON), or a
rename-to-unique-tombstone take (_cas_take — exactly one remover wins). Leases carry
monotonic FENCE numbers (sidecar high-water mark) so an action taken under an expired
lease is detectable (`lease valid --fence N`) — a paused/zombie agent can never silently
corrupt a resource it lost. Unparseable files younger than CORRUPT_GRACE_SECONDS are
mid-writes, not corruption. Deterministic rename destinations are NOT a CAS on Windows
(two renames can both report success) — every tombstone/claim name embeds pid+random.
"""

from pathlib import Path
import heapq
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid

try:
    from scripts.agent_comms import (get_comms_dir, get_hostname,
                                     find_seat_file, clear_seat_cache)
except ImportError:  # direct invocation outside the package
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # a foreign site-packages 'scripts' may have been cached by the attempt above
    sys.modules.pop("scripts", None)
    from scripts.agent_comms import (get_comms_dir, get_hostname,
                                     find_seat_file, clear_seat_cache)

DEFAULT_TTL = 600.0   # 10 minutes — heartbeat-renewed leases never expire while their owner lives

# One value per concern, shared by agent_comms / mcp_server / project_state.
SESSION = os.environ.get("AGENT_SESSION") or uuid.uuid4().hex[:12]
PRESENCE_FRESH_SECONDS = 120        # an agent is "live" if it heartbeated this recently
COLLISION_WINDOW_SECONDS = 300      # cross-workdir same-identity evidence window
CONCURRENT_EVIDENCE_SECONDS = 10    # same-workdir different-session evidence window
GC_PRESENCE_DAYS = 7
GC_TMP_HOURS = 1
GC_PENDING_MINUTES = 10
GC_JOURNAL_DAYS = 14
GC_MAIL_DAYS = 7
GC_UNLINK_BOUND = 500               # max deletions per janitor pass (bounded work)
CORRUPT_GRACE_SECONDS = 5.0         # unparseable + younger than this = a mid-write, NOT corrupt

# The ONE source of truth for the CI check-context names. .github/workflows/ci.yml
# must produce exactly these (job id `test`, matrix os × python); a future
# `collab github-setup --apply` will refuse to require contexts that don't match
# check runs on latest master — mismatched names hard-block ALL merging.
REQUIRED_CHECK_CONTEXTS = ("test (ubuntu-latest, 3.11)", "test (windows-latest, 3.11)")


def _backoff_sleep(attempt: int, base: float = 0.5, cap: float = 15.0) -> None:
    """AWS full-jitter backoff: sleep U(0, min(cap, base * 2^attempt))."""
    time.sleep(random.uniform(0, min(cap, base * (2 ** attempt))))


def atomic_write_json(path: Path, obj, fsync: bool = False) -> None:
    """Atomically replace path with the JSON for obj: readers see the OLD
    complete document or the NEW complete document, never a partial write.
    Windows can raise PermissionError from os.replace while a reader briefly
    holds the destination open — retried 5 times with jitter, then raised
    loudly. Without fsync=True a power loss can still lose the NEW content
    (never produces a torn file); pass fsync=True for must-survive records."""
    tmp = path.with_name(".%s.%d.%d.%s.tmp"
                         % (path.name, time.time_ns(), os.getpid(), os.urandom(4).hex()))
    with open(tmp, "w", encoding="utf-8") as f:  # write-ok: the atomic helper itself
        json.dump(obj, f, indent=2)
        if fsync:
            f.flush()
            os.fsync(f.fileno())
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01 * (attempt + 1) * (1 + random.random()))
    os.replace(tmp, path)   # final attempt raises loudly — never fail silent


def _cas_take(path: Path):
    """Atomically take path OUT OF SERVICE by renaming it to a tombstone.
    Exactly one concurrent caller wins (rename is the CAS). Returns
    (tomb_path, parsed_content) on the win, (None, None) when the file is
    already gone or the take could not be completed. Callers inspect the
    taken content and either proceed (unlink the tomb), restore it via
    open(path, 'x'), or journal the collision."""
    tomb = path.with_name(".%s.tomb.%d.%s" % (path.name, os.getpid(), os.urandom(4).hex()))
    for attempt in range(5):
        try:
            os.replace(path, tomb)
            return tomb, _read_json(tomb)
        except FileNotFoundError:
            return None, None
        except PermissionError:
            time.sleep(0.01 * (attempt + 1) * (1 + random.random()))
    return None, None   # could not take — caller treats as lost-the-race


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
    """None ⇔ absent or genuinely corrupt — never mid-write, never a transient
    Windows sharing violation (those are retried: a reader's open() racing an
    os.replace can briefly be denied)."""
    for attempt in range(5):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except PermissionError:
            time.sleep(0.005 * (attempt + 1))
        except Exception:
            return None
    return None


# ── presence + identity-collision detection ──────────────────────────────────────────────────
def heartbeat(who: str, status: str = "active", task: str = "", project: str = "default"):
    """Presence beat carrying the WORKDIR + SESSION. Returns (payload, warning_or_None).
    Collision evidence, either of:
      - same identity beating from a DIFFERENT workdir within COLLISION_WINDOW_SECONDS
        (two seats sharing one call-sign — leases cannot protect them from each other);
      - same workdir but a DIFFERENT live session within CONCURRENT_EVIDENCE_SECONDS
        (two concurrent processes in one seat; a sequential restart is NOT a collision)."""
    presence_file = get_comms_dir() / f"{who}.json"
    warning = None
    prev = _read_json(presence_file)
    cwd = str(Path.cwd())
    age = _now() - prev.get("timestamp", 0) if prev else None
    if prev and prev.get("workdir") and prev["workdir"] != cwd \
            and age < COLLISION_WINDOW_SECONDS:
        warning = ("IDENTITY COLLISION: '%s' heartbeated from '%s' %ds ago and is now beating "
                   "from '%s'. Two sessions are sharing one identity — leases CANNOT protect "
                   "them from each other. Run `mcp collab seat new <callsign>` to give this "
                   "session its own worktree + call-sign." % (who, prev["workdir"], int(age), cwd))
        journal_log(project, who, "identity.collision",
                    {"previous_workdir": prev["workdir"], "current_workdir": cwd})
    elif prev and prev.get("workdir") == cwd and prev.get("session") \
            and prev["session"] != SESSION and age < CONCURRENT_EVIDENCE_SECONDS:
        warning = ("IDENTITY COLLISION: two live processes are beating '%s' from the same "
                   "workdir '%s' (sessions %s and %s). One seat = one agent process group; "
                   "give the second agent its own seat (`mcp collab seat new <callsign>`)."
                   % (who, cwd, prev["session"], SESSION))
        journal_log(project, who, "identity.collision",
                    {"workdir": cwd, "sessions": [prev["session"], SESSION]})
    payload = {"hostname": who, "timestamp": _now(), "status": status,
               "current_task": task, "last_seen": time.ctime(),
               "workdir": cwd, "session": SESSION, "v": 2}
    atomic_write_json(presence_file, payload)
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


def _fence_path(project: str, resource: str) -> Path:
    return lease_path(project, resource).with_suffix(".fence.json")


def _fence_read(project: str, resource: str) -> int:
    data = _read_json(_fence_path(project, resource))
    return int(data.get("fence", 0)) if data else 0


def _fence_bump(project: str, resource: str, new_fence: int):
    """Record the fence high-water mark (monotonic max; lower values never win)."""
    if new_fence > _fence_read(project, resource):
        atomic_write_json(_fence_path(project, resource),
                          {"fence": new_fence, "updated": _now()})


def _file_age(path: Path) -> float:
    try:
        return _now() - path.stat().st_mtime
    except OSError:
        return 1e9   # vanished — callers' CAS paths resolve the race


def _restore_or_journal(path: Path, tomb: Path, parsed, project: str, who: str, kind: str):
    """Put a taken-by-mistake record back (parsed=None restores the raw bytes —
    e.g. a mid-write foreign create we must not destroy). If a third party
    occupied the slot in the gap, journal the collision instead — the displaced
    owner discovers the loss at its next fenced renew/validity check (that is
    what fencing is for)."""
    try:
        if parsed is not None:
            with open(path, "x", encoding="utf-8") as f:
                json.dump(parsed, f, indent=2)
        else:
            with open(path, "xb") as f:
                f.write(tomb.read_bytes())
    except FileExistsError:
        journal_log(project, who, kind + ".break_collision",
                    {"path": path.name, "displaced_owner": (parsed or {}).get("owner"),
                     "displaced_fence": (parsed or {}).get("fence")})
    except OSError:
        pass
    try:
        tomb.unlink()
    except OSError:
        pass


def lease_acquire(project: str, resource: str, who: str, ttl: float = DEFAULT_TTL, note: str = ""):
    """Atomically acquire (re-entrant for the owner in the SAME workdir; stale and
    corrupt leases are broken via rename-CAS, never bare unlink). Every successful
    acquire mints a FENCE strictly greater than every previous holder's — actions
    taken under an expired lease are detectable via lease_valid(fence).
    Returns (ok, lease_dict_or_holder)."""
    path = lease_path(project, resource)
    cwd = str(Path.cwd())
    for attempt in range(8):
        if attempt:
            _backoff_sleep(attempt, base=0.05, cap=1.0)
        current = lease_info(project, resource)
        # Unparseable + young = a foreign create mid-write, NOT corruption: back
        # off and re-read instead of destroying a just-born live lease.
        corrupt = (current is None and path.exists()
                   and _file_age(path) > CORRUPT_GRACE_SECONDS)
        if current:
            if current.get("owner") == who:
                if current.get("workdir") not in (None, cwd):
                    refusal = ("identity '%s' already holds '%s' from workdir '%s' — this is a "
                               "DIFFERENT seat. Run `mcp collab seat init` (same dir) or "
                               "`mcp collab seat new <callsign>` (new worktree)."
                               % (who, resource, current.get("workdir")))
                    journal_log(project, who, "identity.refused",
                                {"resource": resource, "their_workdir": current.get("workdir"),
                                 "my_workdir": cwd})
                    return False, dict(current, refusal=refusal)
                if not current["stale"]:
                    return lease_renew(project, resource, who)    # re-entrant, same seat
                # Our OWN lease expired: fall through to the CAS-take path so the
                # re-acquisition mints a strictly HIGHER fence — a renew/recreate
                # here could resurrect the old incarnation over a competitor who
                # legitimately broke the stale lease in the meantime.
            elif not current["stale"]:
                return False, current                              # held by a LIVE other
        if current or corrupt:                                     # stale/corrupt → CAS-take
            tomb, parsed = _cas_take(path)
            if tomb is None:
                continue                                           # lost the break race
            if parsed and parsed.get("owner") and not _lease_stale(parsed):
                # owner renewed between our read and our take — put it back
                _restore_or_journal(path, tomb, parsed, project, who, "lease")
                return False, lease_info(project, resource) or parsed
            try:
                tomb.unlink()
            except OSError:
                pass
            journal_log(project, who,
                        "lease.broke_corrupt" if corrupt and not parsed else "lease.broke_stale",
                        {"resource": resource,
                         "previous_owner": (parsed or {}).get("owner"),
                         "previous_fence": (parsed or {}).get("fence")})
        taken_fence = int((parsed or {}).get("fence", 0)) if (current or corrupt) else 0
        fence = max(_fence_read(project, resource), taken_fence) + 1
        payload = {"resource": resource, "owner": who, "workdir": cwd, "session": SESSION,
                   "acquired": _now(), "renewed": _now(), "ttl": ttl, "note": note,
                   "fence": fence, "v": 2}
        try:
            with open(path, "x", encoding="utf-8") as f:           # O_EXCL: atomic on NTFS/POSIX
                json.dump(payload, f, indent=2)
            _fence_bump(project, resource, fence)
            journal_log(project, who, "lease.acquired",
                        {"resource": resource, "note": note, "fence": fence})
            return True, payload
        except FileExistsError:
            continue                                               # lost the race — re-evaluate
    return False, lease_info(project, resource)


def _lease_stale(raw: dict) -> bool:
    """Staleness from a RAW payload (no derived fields)."""
    age = _now() - float(raw.get("renewed", raw.get("acquired", 0)))
    return age >= float(raw.get("ttl", DEFAULT_TTL))


def lease_renew(project: str, resource: str, who: str, fence=None):
    """Renew ONLY the same LIVE incarnation, as a CAS: the lease file is taken
    (rename), re-verified against the TAKEN content — not an earlier read —
    and recreated. A renew can therefore never resurrect an expired lease and
    never clobber a competitor who legitimately broke + re-acquired it in the
    read→write window (the adversarial-review critical finding)."""
    path = lease_path(project, resource)
    current = lease_info(project, resource)
    if not current or current.get("owner") != who:
        return False, current
    if fence is not None and int(current.get("fence", 0)) != int(fence):
        return False, dict(current, refusal="your lease was broken and re-acquired "
                                             "(fence moved) — stop work and re-acquire")
    if current.get("workdir") not in (None, str(Path.cwd())):
        return False, dict(current, refusal="this identity holds the lease from another "
                                            "workdir — one seat = one agent")
    if current["stale"]:
        return False, dict(current, refusal="lease expired — a renew cannot resurrect it; "
                                            "re-acquire to mint a new fence")
    tomb, parsed = _cas_take(path)
    if tomb is None:
        return False, lease_info(project, resource)
    same = (parsed and parsed.get("owner") == who and not _lease_stale(parsed)
            and int(parsed.get("fence", 0)) == int(current.get("fence", 0))
            and (fence is None or int(parsed.get("fence", 0)) == int(fence)))
    if not same:
        _restore_or_journal(path, tomb, parsed, project, who, "lease")
        return False, parsed or lease_info(project, resource)
    renewed = dict(parsed, renewed=_now())
    try:
        with open(path, "x", encoding="utf-8") as f:
            json.dump(renewed, f, indent=2)
    except FileExistsError:                        # third party occupied the gap
        journal_log(project, who, "lease.renew_collision",
                    {"resource": resource, "fence": parsed.get("fence")})
        try:
            tomb.unlink()
        except OSError:
            pass
        return False, lease_info(project, resource)
    try:
        tomb.unlink()
    except OSError:
        pass
    return True, renewed


def lease_valid(project: str, resource: str, who: str, fence) -> tuple:
    """True iff WE still hold THIS incarnation right now (owner + fence match,
    not stale). Call immediately before any irreversible side effect."""
    current = lease_info(project, resource)
    ok = bool(current and current.get("owner") == who
              and int(current.get("fence", 0)) == int(fence)
              and not current["stale"])
    return ok, current


def lease_release(project: str, resource: str, who: str, fence=None):
    """Release via rename-CAS: take the file, verify the taken content is OURS
    (or stale), and only then retire it. A live foreign lease is restored."""
    path = lease_path(project, resource)
    current = lease_info(project, resource)
    if not current and not path.exists():
        return True, None
    tomb, parsed = _cas_take(path)
    if tomb is None:
        return True, None                                          # already gone
    if parsed is None and _file_age(tomb) <= CORRUPT_GRACE_SECONDS:
        _restore_or_journal(path, tomb, None, project, who, "lease")   # mid-write foreign create
        return False, None
    ours = parsed and parsed.get("owner") == who \
        and (fence is None or int(parsed.get("fence", 0)) == int(fence))
    if parsed and not ours and not _lease_stale(parsed):
        _restore_or_journal(path, tomb, parsed, project, who, "lease")
        return False, parsed
    # record the retired fence in the sidecar: even if the acquire that minted
    # it crashed before its own bump, the high-water mark survives retirement
    _fence_bump(project, resource, int((parsed or {}).get("fence", 0) or 0))
    try:
        tomb.unlink()
    except OSError:
        pass
    journal_log(project, who, "lease.released",
                {"resource": resource, "fence": (parsed or {}).get("fence")})
    return True, None


def lease_break(project: str, resource: str, who: str):
    """Break ONLY a stale or corrupt lease (a live owner's lease cannot be stolen).
    Corrupt files are genuinely cleared — the resource can never deadlock."""
    path = lease_path(project, resource)
    current = lease_info(project, resource)
    if not current and not path.exists():
        return True, None
    if current and not current["stale"]:
        return False, current
    if current is None and path.exists() and _file_age(path) <= CORRUPT_GRACE_SECONDS:
        return False, None                       # mid-write foreign create, not a corpse
    tomb, parsed = _cas_take(path)
    if tomb is None:
        return True, None
    if parsed and not _lease_stale(parsed):
        _restore_or_journal(path, tomb, parsed, project, who, "lease")
        return False, parsed
    _fence_bump(project, resource, int((parsed or {}).get("fence", 0) or 0))
    try:
        tomb.unlink()
    except OSError:
        pass
    journal_log(project, who, "lease.broke_stale",
                {"resource": resource, "previous_owner": (parsed or {}).get("owner"),
                 "previous_fence": (parsed or {}).get("fence")})
    return True, None


def leases_all(project: str):
    out = {}
    for f in (collab_dir(project) / "leases").glob("*.json"):
        if f.name.endswith(".fence.json"):
            continue                                   # fence sidecar, not a lease
        data = lease_info(project, f.stem)
        if data:
            out[data.get("resource", f.stem)] = data
    return out


# ── claims (advisory work-area ownership) ─────────────────────────────────────────────────────
def _claim_path(project: str, claim_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in claim_id)
    return collab_dir(project) / "claims" / f"{safe}.json"


def claim_add(project: str, claim_id: str, pattern: str, who: str, note: str = ""):
    """O_EXCL create is the CAS: exactly one concurrent claimant wins. The
    owner (same workdir) may refresh; corrupt claims self-heal."""
    if not claim_id or not pattern:
        return False, {"owner": "nobody — a claim needs a non-empty id and pattern"}
    path = _claim_path(project, claim_id)
    cwd = str(Path.cwd())
    payload = {"id": claim_id, "pattern": pattern, "owner": who, "workdir": cwd,
               "session": SESSION, "note": note, "time": _now(), "v": 2}
    for attempt in range(5):
        try:
            with open(path, "x", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            journal_log(project, who, "claim.added",
                        {"id": claim_id, "pattern": pattern, "note": note})
            return True, payload
        except FileExistsError:
            existing = _read_json(path)
            if existing is None and path.exists():
                if _file_age(path) <= CORRUPT_GRACE_SECONDS:       # mid-write → re-read shortly
                    _backoff_sleep(attempt, base=0.02, cap=0.3)
                    continue
                tomb, _ = _cas_take(path)                          # genuinely corrupt → clear
                if tomb is not None:
                    try:
                        tomb.unlink()
                    except OSError:
                        pass
                    journal_log(project, who, "claim.broke_corrupt", {"id": claim_id})
                _backoff_sleep(attempt, base=0.05, cap=0.5)
                continue
            if existing and existing.get("owner") == who:
                if existing.get("workdir") not in (None, cwd):
                    journal_log(project, who, "identity.refused",
                                {"claim": claim_id, "their_workdir": existing.get("workdir")})
                    return False, dict(existing, refusal=(
                        "identity '%s' already owns claim '%s' from workdir '%s' — a different "
                        "seat. Use your own call-sign (`mcp collab seat new`)."
                        % (who, claim_id, existing.get("workdir"))))
                # refresh as a CAS: take, re-verify the TAKEN content is still
                # ours, recreate — a blind rewrite could clobber a competitor
                # who dropped + re-claimed in the read→write window
                tomb, parsed = _cas_take(path)
                if tomb is None:
                    _backoff_sleep(attempt, base=0.02, cap=0.3)
                    continue
                if not parsed or parsed.get("owner") != who:
                    _restore_or_journal(path, tomb, parsed, project, who, "claim")
                    return False, parsed or existing
                refreshed = dict(parsed, pattern=pattern, note=note, session=SESSION, v=2)
                try:
                    with open(path, "x", encoding="utf-8") as f:   # keep the original time
                        json.dump(refreshed, f, indent=2)
                except FileExistsError:
                    journal_log(project, who, "claim.refresh_collision", {"id": claim_id})
                    try:
                        tomb.unlink()
                    except OSError:
                        pass
                    return False, _read_json(path)
                try:
                    tomb.unlink()
                except OSError:
                    pass
                return True, refreshed
            return False, existing
    return False, _read_json(path)


def claim_drop(project: str, claim_id: str, who: str):
    """Drop via rename-CAS: take, verify the taken content is droppable
    (ours, or stale > 24h), restore if it turns out fresh and foreign."""
    path = _claim_path(project, claim_id)
    if not path.exists():
        journal_log(project, who, "claim.dropped", {"id": claim_id})
        return True, None
    tomb, parsed = _cas_take(path)
    if tomb is None:
        return True, None                                          # already gone
    if parsed is None and _file_age(tomb) <= CORRUPT_GRACE_SECONDS:
        _restore_or_journal(path, tomb, None, project, who, "claim")   # mid-write foreign create
        return False, None
    if parsed and parsed.get("owner") not in (who, None):
        age_h = (_now() - parsed.get("time", 0)) / 3600.0
        if age_h < 24:                                             # fresh + foreign → restore
            _restore_or_journal(path, tomb, parsed, project, who, "claim")
            return False, parsed
    try:
        tomb.unlink()
    except OSError:
        pass
    journal_log(project, who, "claim.dropped", {"id": claim_id})
    return True, None


def claims_all(project: str):
    return [c for f in (collab_dir(project) / "claims").glob("*.json")
            if (c := _read_json(f))]


# ── journal (the team's radio channel) ────────────────────────────────────────────────────────
JOURNAL_ROTATE_BYTES = 2 * 1024 * 1024   # rotate at 2 MB so the radio channel never bloats
JOURNAL_DATA_BOUND = 2048                # bound a single event's serialized data
_TAIL_READ_BYTES = 65536                 # per-file read bound when tailing


def _journal_dir(project: str) -> Path:
    d = collab_dir(project) / "journal"
    d.mkdir(exist_ok=True)
    return d


def journal_log(project: str, who: str, event: str, data=None):
    """Append to THIS PROCESS's own segment (identity + pid in the name =
    single-writer by construction; 100 concurrent writers never share a file).
    One raw O_APPEND syscall per event. Rotation = unique rename (the CAS)."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in who) or "anon"
    seg = _journal_dir(project) / ("%s.%d.ndjson" % (safe, os.getpid()))
    try:
        if seg.exists() and seg.stat().st_size > JOURNAL_ROTATE_BYTES:
            seg.rename(seg.with_name("%s.%d.ndjson"
                                     % (seg.stem, time.time_ns() // 1_000_000)))
    except OSError:
        pass   # rotation is best-effort; never lose the event over it
    payload = data or {}
    serialized = json.dumps(payload, ensure_ascii=False)
    if len(serialized.encode("utf-8")) > JOURNAL_DATA_BOUND:
        payload = {"truncated": True, "head": serialized[:JOURNAL_DATA_BOUND]}
    line = json.dumps({"t": _now(), "ts": time.ctime(), "who": who,
                       "event": event, "data": payload}, ensure_ascii=False)
    fd = os.open(seg, os.O_APPEND | os.O_CREAT | os.O_WRONLY)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _tail_events(path: Path):
    """Last events of one journal file, bounded read, torn/corrupt lines skipped."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            offset = max(0, size - _TAIL_READ_BYTES)
            f.seek(offset)
            chunk = f.read().decode("utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return []
    lines = chunk.splitlines()
    if offset > 0 and lines:
        lines = lines[1:]                      # first line is almost surely partial
    out = []
    for raw in lines:
        try:
            e = json.loads(raw)
            if isinstance(e, dict) and "event" in e:
                out.append(e)
        except Exception:
            pass                               # torn tail / corrupt line: documented skip
    return out


def journal_tail(project: str, n: int = 20):
    """Merged tail across every writer's segment plus the legacy single files
    (read forever, written never). Order is wall-clock — exact on one machine,
    advisory across machines (clock skew)."""
    base = collab_dir(project)
    candidates = [base / "journal.ndjson", base / "journal.1.ndjson"]
    candidates += sorted((base / "journal").glob("*.ndjson")) if (base / "journal").is_dir() else []
    streams = [s for s in (_tail_events(p) for p in candidates) if s]
    merged = list(heapq.merge(*streams, key=lambda e: e.get("t", 0)))
    return merged[-n:]


# ── work (GitHub issues checked out like leases — gh-backed) ──────────────────────────────────
GH_TIMEOUT = 30
WORK_STALE_HOURS = 24.0   # someone else's checkout may be dropped after this long


def _fake_gh_apply(state: dict, gh_args):
    """Pure fake-gh verb logic over a state dict {'issues': {'<n>': {...}}, 'offline': bool}.
    Shared by the in-memory selftest fake and the file-backed COLLAB_FAKE_GH fake
    (issue keys are STRINGS so the same logic works on JSON-loaded state)."""
    if state.get("offline"):
        return False, "gh CLI not found — offline fake"
    issues = state.setdefault("issues", {})
    head = gh_args[:2]
    if head == ["issue", "view"]:
        k = str(int(gh_args[2]))
        if k not in issues:
            return False, "issue #%s not found" % k
        iss = issues[k]
        return True, json.dumps({"number": int(k), "title": iss.get("title", ""),
                                 "url": iss.get("url", ""), "body": iss.get("body", ""),
                                 "labels": [{"name": x} for x in iss.get("labels", [])],
                                 "assignees": []})
    if head == ["issue", "edit"]:
        if state.get("fail_edit"):
            return False, "forced edit failure (selftest)"
        iss = issues[str(int(gh_args[2]))]
        if "--add-label" in gh_args:
            new = gh_args[gh_args.index("--add-label") + 1].split(",")
            iss["labels"] = sorted(set(iss.get("labels", [])) | set(new))
        if "--remove-label" in gh_args:
            gone = set(gh_args[gh_args.index("--remove-label") + 1].split(","))
            iss["labels"] = [x for x in iss.get("labels", []) if x not in gone]
        if "--body" in gh_args:
            iss["body"] = gh_args[gh_args.index("--body") + 1]
        return True, ""
    if head == ["issue", "close"]:
        issues[str(int(gh_args[2]))]["state"] = "closed"
        return True, ""
    if head == ["issue", "comment"]:
        issues[str(int(gh_args[2]))].setdefault("comments", []).append(
            gh_args[gh_args.index("--body") + 1])
        return True, ""
    if head == ["issue", "list"]:
        return True, json.dumps(
            [{"number": int(k), "title": v.get("title", ""), "url": v.get("url", ""),
              "assignees": [], "labels": [{"name": x} for x in v.get("labels", [])]}
             for k, v in issues.items() if v.get("state", "open") == "open"])
    if gh_args[:1] == ["label"]:
        return True, ""
    return False, "fake gh: unhandled %s" % " ".join(gh_args[:3])


def _file_fake_gh(state_path: Path, gh_args):
    """File-backed fake gh: many PROCESSES (swarm workers, E2E runs) share one
    issue store. Reads are lock-free atomic-snapshot reads; mutations serialize
    on an O_EXCL .lock sidecar with a 5s stale-break (a watchdog-killed worker
    must never wedge the fake forever)."""
    mutating = (gh_args[:2] in (["issue", "edit"], ["issue", "close"], ["issue", "comment"])
                or gh_args[:1] == ["label"])
    if not mutating:
        state = _read_json(state_path)
        if state is None:
            return False, "fake gh state unreadable: %s" % state_path
        return _fake_gh_apply(state, gh_args)
    lock = state_path.with_name(state_path.name + ".lock")
    acquired = False
    for _ in range(60):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            acquired = True
            break
        except FileExistsError:
            try:
                if _now() - lock.stat().st_mtime > 5.0:
                    tomb, _ = _cas_take(lock)
                    if tomb is not None:
                        try:
                            tomb.unlink()
                        except OSError:
                            pass
                    continue
            except OSError:
                pass
            time.sleep(0.025)
    if not acquired:
        return False, "fake gh lock wedged at %s" % lock
    try:
        state = _read_json(state_path)
        if state is None:
            return False, "fake gh state unreadable: %s" % state_path
        ok, out = _fake_gh_apply(state, gh_args)
        atomic_write_json(state_path, state)
        return ok, out
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _gh_real(gh_args):
    """Run the gh CLI. Returns (ok, stdout_or_error). This is the ONLY GitHub
    touchpoint of the work verbs. COLLAB_FAKE_GH=<state.json> diverts every
    call to the file-backed fake (E2E/swarm runs hit no network)."""
    fake_state = os.environ.get("COLLAB_FAKE_GH")
    if fake_state:
        if not Path(fake_state).exists():
            return False, "COLLAB_FAKE_GH points at a missing state file: %s" % fake_state
        return _file_fake_gh(Path(fake_state), gh_args)
    exe = shutil.which("gh")
    if not exe:
        return False, ("gh CLI not found — `collab work` needs GitHub CLI "
                       "(https://cli.github.com) authenticated via `gh auth login`. "
                       "Leases/claims/journal work without it.")
    try:
        proc = subprocess.run([exe] + gh_args, capture_output=True, text=True,
                              timeout=GH_TIMEOUT, encoding="utf-8", errors="replace")
    except Exception as e:                                 # no network, timeout, ...
        return False, "gh did not run: %s" % e
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "gh exited %d" % proc.returncode).strip()
    return True, proc.stdout


GH_RUNNER = _gh_real    # the documented EXTERNAL swap seam; in-tree code passes runner= instead


def _gh_json(gh_args, runner=None):
    ok, out = (runner or GH_RUNNER)(gh_args)
    if not ok:
        return False, out
    try:
        return True, json.loads(out)
    except Exception as e:
        return False, "unparseable gh output: %s" % e


def work_dir(project: str) -> Path:
    d = collab_dir(project) / "work"
    d.mkdir(exist_ok=True)
    return d


def work_path(project: str, issue) -> Path:
    return work_dir(project) / ("issue-%d.json" % int(issue))


def work_all(project: str):
    return [w for f in sorted(work_dir(project).glob("issue-*.json"))
            if (w := _read_json(f))]


_PATH_TOKEN_RE = re.compile(r"[\w.\-/\\]+\.[A-Za-z][A-Za-z0-9]{0,5}\b")
_BARE_FILE_EXTS = {"py", "md", "js", "ts", "tsx", "jsx", "json", "yml", "yaml", "toml",
                   "txt", "rs", "go", "java", "c", "h", "cpp", "hpp", "cs", "rb", "sh",
                   "ps1", "html", "css"}


def extract_paths(text: str):
    """File-path-looking tokens in free text (issue bodies, PR descriptions) —
    shared by `work start` claim patterns and the auto-impact workflow."""
    hits, seen = [], set()
    for m in _PATH_TOKEN_RE.finditer(text or ""):
        tok = m.group(0).strip(".")
        ext = tok.rsplit(".", 1)[-1].lower()
        pathish = "/" in tok or "\\" in tok or ext in _BARE_FILE_EXTS
        if pathish and tok.lower() not in seen:
            seen.add(tok.lower())
            hits.append(tok)
    return hits


def work_conflicts(project: str):
    """Conflict radar: pairs of checked-out issues whose touched-path sets intersect."""
    ws = work_all(project)
    out = []
    for i in range(len(ws)):
        for j in range(i + 1, len(ws)):
            a, b = ws[i], ws[j]
            overlap = sorted(set(a.get("paths", [])) & set(b.get("paths", [])))
            if overlap:
                out.append((a["issue"], a["owner"], b["issue"], b["owner"], overlap))
    return out


def work_start(project: str, issue, who: str, make_branch: bool = False, runner=None):
    """Check OUT a GitHub issue like a lease. Transactional order: local truth
    settles atomically (claim + O_EXCL pending record) BEFORE slow gh mutations;
    a hard gh failure rolls everything back — no silent local/GitHub divergence.
    Returns (ok, message)."""
    issue = int(issue)
    run = runner or GH_RUNNER
    cwd = str(Path.cwd())
    wpath = work_path(project, issue)
    rec = _read_json(wpath)
    if rec and rec.get("owner") != who:
        age_h = (_now() - rec.get("started", 0)) / 3600.0
        if age_h < WORK_STALE_HOURS:
            return False, ("issue #%d is checked out by %s (%.1fh ago) — coordinate via "
                           "collab message/journal, or `work drop %d` once it is stale"
                           % (issue, rec.get("owner"), age_h, issue))
        tomb, parsed = _cas_take(wpath)                    # stale takeover via rename-CAS
        if tomb is not None:
            try:
                tomb.unlink()
            except OSError:
                pass
            journal_log(project, who, "work.took_stale",
                        {"issue": issue, "previous_owner": (parsed or {}).get("owner")})
    elif rec and rec.get("owner") == who and rec.get("workdir") not in (None, cwd):
        journal_log(project, who, "identity.refused",
                    {"issue": issue, "their_workdir": rec.get("workdir")})
        return False, ("identity '%s' already has issue #%d checked out from workdir '%s' — "
                       "a different seat. Run `mcp collab seat new <callsign>`."
                       % (who, issue, rec.get("workdir")))
    ok, meta = _gh_json(["issue", "view", str(issue),
                         "--json", "number,title,url,body,labels,assignees"], runner=run)
    if not ok:
        return False, meta
    fetched_labels = {lab.get("name", "") for lab in meta.get("labels", [])}
    foreign_agents = {x for x in fetched_labels
                      if x.startswith("agent:") and x != "agent:" + who}
    if "in-progress" in fetched_labels and (foreign_agents or not _read_json(wpath)):
        holder = ", ".join(sorted(foreign_agents)) or "another agent"
        return False, ("issue #%d already carries the in-progress label on GitHub — checked "
                       "out by %s (possibly on another machine). Pick different work."
                       % (issue, holder))
    title, url = meta.get("title", ""), meta.get("url", "")
    paths = extract_paths(meta.get("body", ""))[:8]
    pattern = ",".join(paths) if paths else url
    c_ok, c_info = claim_add(project, "issue-%d" % issue, pattern, who,
                             note="%s — %s" % (title, url))
    if not c_ok:
        return False, ("claim issue-%d is held by %s — that agent owns this issue's area"
                       % (issue, (c_info or {}).get("owner")))
    pending = {"issue": issue, "title": title, "url": url, "owner": who, "workdir": cwd,
               "session": SESSION, "paths": paths, "branch": "", "phase": "pending",
               "started": _now(), "started_ts": time.ctime(), "v": 2}
    try:
        with open(wpath, "x", encoding="utf-8") as f:      # O_EXCL: one checkout winner
            json.dump(pending, f, indent=2)
    except FileExistsError:
        time.sleep(0.05)                                   # may be a mid-write foreign create
        other = _read_json(wpath)
        if not other or other.get("owner") != who:
            claim_drop(project, "issue-%d" % issue, who)   # roll back our claim
            return False, ("lost the checkout race for issue #%d to %s"
                           % (issue, (other or {}).get("owner") or "another agent"))
    labels = "in-progress,agent:" + who
    lab_ok, lab_err = run(["issue", "edit", str(issue), "--add-label", labels,
                           "--add-assignee", "@me"])
    if not lab_ok:                       # labels may not exist in the repo yet — create, retry
        run(["label", "create", "in-progress", "--color", "FBCA04", "--force"])
        run(["label", "create", "agent:" + who, "--color", "1D76DB", "--force"])
        lab_ok, lab_err = run(["issue", "edit", str(issue), "--add-label", labels])
        if not lab_ok:                                     # hard gh failure → ROLL BACK
            tomb, _ = _cas_take(wpath)
            if tomb is not None:
                try:
                    tomb.unlink()
                except OSError:
                    pass
            claim_drop(project, "issue-%d" % issue, who)
            journal_log(project, who, "work.rolled_back",
                        {"issue": issue, "reason": str(lab_err)[:200]})
            return False, "gh labeling failed — checkout rolled back: %s" % lab_err
    branch, branch_err = "", ""
    if make_branch:
        branch = "agent/%s/issue-%d" % (who, issue)
        try:
            subprocess.run(["git", "checkout", "-b", branch], capture_output=True,
                           text=True, timeout=30, check=True)
        except Exception as e:
            branch, branch_err = "", str(e)
    payload = dict(pending, branch=branch, phase="active")
    atomic_write_json(wpath, payload)
    journal_log(project, who, "work.start",
                {"issue": issue, "title": title, "url": url, "paths": paths})
    msg = ("checked out issue #%d: %s\n  url: %s\n  claim: issue-%d -> %s"
           % (issue, title, url, issue, pattern))
    if branch:
        msg += "\n  branch: %s" % branch
    elif branch_err:
        msg += "\n  [warn] branch not created: %s" % branch_err
    for ia, oa, ib, ob, ov in work_conflicts(project):
        if issue in (ia, ib):
            msg += ("\n  [CONFLICT RADAR] #%d (%s) and #%d (%s) both touch: %s"
                    % (ia, oa, ib, ob, ", ".join(ov[:5])))
    return True, msg


def _work_retire(project: str, issue: int, who: str):
    """Take the work record out of service (rename-CAS, owner-verified)."""
    tomb, parsed = _cas_take(work_path(project, issue))
    if tomb is None:
        return True
    if parsed is None and _file_age(tomb) <= CORRUPT_GRACE_SECONDS:
        _restore_or_journal(work_path(project, issue), tomb, None, project, who, "work")
        return False
    if parsed and parsed.get("owner") not in (who, None):
        _restore_or_journal(work_path(project, issue), tomb, parsed, project, who, "work")
        return False
    try:
        tomb.unlink()
    except OSError:
        pass
    return True


def work_done(project: str, issue, who: str, pr: str = "", runner=None):
    """Finish a checkout: close the issue (or link the PR and leave it open for
    review), drop the claim + record, journal work.done. Returns (ok, message)."""
    issue = int(issue)
    run = runner or GH_RUNNER
    rec = _read_json(work_path(project, issue))
    if rec and rec.get("owner") != who:
        return False, ("issue #%d is checked out by %s — only its owner finishes it"
                       % (issue, rec.get("owner")))
    if pr:
        ok, err = run(["issue", "comment", str(issue), "--body",
                       "Agent `%s` finished this work: %s" % (who, pr)])
        if ok:
            run(["issue", "edit", str(issue), "--remove-label", "in-progress"])
    else:
        ok, err = run(["issue", "close", str(issue), "--comment",
                       "Completed by agent `%s` (mcp collab work done)." % who])
    if not ok:
        return False, err
    run(["issue", "edit", str(issue), "--remove-label", "agent:" + who])  # best-effort
    claim_drop(project, "issue-%d" % issue, who)
    _work_retire(project, issue, who)
    journal_log(project, who, "work.done", {"issue": issue, "pr": pr})
    return True, ("issue #%d done — linked %s (left open for review)" % (issue, pr)
                  if pr else "issue #%d closed" % issue)


def work_drop(project: str, issue, who: str, runner=None):
    """Un-checkout without finishing: unlabel, drop the claim + record, journal."""
    issue = int(issue)
    run = runner or GH_RUNNER
    rec = _read_json(work_path(project, issue))
    if rec and rec.get("owner") != who:
        age_h = (_now() - rec.get("started", 0)) / 3600.0
        if age_h < WORK_STALE_HOURS:
            return False, ("issue #%d is checked out by %s (%.1fh ago) — not stale yet"
                           % (issue, rec.get("owner"), age_h))
    owner = (rec or {}).get("owner", who)
    run(["issue", "edit", str(issue),
         "--remove-label", "in-progress,agent:" + owner])                 # best-effort
    claim_drop(project, "issue-%d" % issue, who)
    _work_retire(project, issue, who)
    journal_log(project, who, "work.drop", {"issue": issue, "owner": owner})
    return True, "issue #%d released" % issue


def work_list(project: str, who: str, runner=None):
    """Open issues + who has them checked out locally. Returns (ok, text)."""
    ok, issues = _gh_json(["issue", "list", "--state", "open", "--limit", "200",
                           "--json", "number,title,labels,assignees,url"], runner=runner)
    if not ok:
        return False, issues
    local = {w["issue"]: w for w in work_all(project)}
    lines = []
    for it in issues:
        n = it.get("number")
        labs = ",".join(lab.get("name", "") for lab in it.get("labels", []))
        asg = ",".join(a.get("login", "") for a in it.get("assignees", []))
        mark = ""
        if n in local:
            o = local[n].get("owner")
            mark = "  <- checked out by " + ("YOU" if o == who else str(o))
        lines.append("#%-5d %s  [%s]%s%s" % (n, it.get("title", "")[:60], labs,
                                             (" @" + asg) if asg else "", mark))
    for ia, oa, ib, ob, ov in work_conflicts(project):
        lines.append("[CONFLICT RADAR] #%d (%s) and #%d (%s) both touch: %s"
                     % (ia, oa, ib, ob, ", ".join(ov[:5])))
    return True, "\n".join(lines) or "(no open issues)"


def work_tick(project: str, issue, item, who: str, runner=None):
    """Tick the item-th task-list checkbox (1-based) inside the issue body."""
    issue, item = int(issue), int(item)
    run = runner or GH_RUNNER
    ok, meta = _gh_json(["issue", "view", str(issue), "--json", "body,title"], runner=run)
    if not ok:
        return False, meta
    body = meta.get("body") or ""
    boxes = list(re.finditer(r"(?m)^(\s*(?:[-*+]|\d+\.)\s*\[)([ xX])(\])", body))
    if item < 1 or item > len(boxes):
        return False, "issue #%d has %d checkbox(es); no item %d" % (issue, len(boxes), item)
    m = boxes[item - 1]
    line_end = body.find("\n", m.end())
    line = body[m.start():line_end if line_end != -1 else len(body)].strip()
    if m.group(2).lower() == "x":
        return True, "item %d is already ticked: %s" % (item, line[:80])
    new_body = body[:m.start(2)] + "x" + body[m.end(2):]
    ok, err = run(["issue", "edit", str(issue), "--body", new_body])
    if not ok:
        return False, err
    journal_log(project, who, "work.tick", {"issue": issue, "item": item, "text": line[:120]})
    return True, "ticked #%d item %d: %s" % (issue, item, line[:80])


# ── seats (same-device multi-agent identity) ──────────────────────────────────────────────────
SEAT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}$")   # no underscores: legacy mailbox delimiter


def seat_init(callsign: str = None, workdir=None, project: str = "default"):
    """Bind THIS workdir to a call-sign via .mcp/seat.json. The seat file is
    create-once (O_EXCL) — it is the atomic occupancy arbiter for the workdir,
    which is what makes N agents on ONE device structurally safe: identity no
    longer collapses to the shared hostname. Returns (ok, identity_or_error)."""
    wd = Path(workdir or Path.cwd()).resolve()
    spath = wd / ".mcp" / "seat.json"
    existing = _read_json(spath)
    if existing:
        if callsign and existing.get("identity") != callsign:
            return False, ("this workdir is already seat '%s' — one workdir = one agent. "
                           "Run `mcp collab seat new %s` for a fresh worktree seat."
                           % (existing.get("identity"), callsign))
        clear_seat_cache()
        return True, existing.get("identity")
    # presence evidence: a DIFFERENT live identity already works from this dir
    for f in get_comms_dir().glob("*.json"):
        d = _read_json(f)
        if not d or "timestamp" not in d:
            continue
        if d.get("workdir") == str(wd) \
                and (_now() - d.get("timestamp", 0)) < PRESENCE_FRESH_SECONDS \
                and d.get("hostname") != callsign:
            return False, ("workdir '%s' is the live seat of '%s' — get your own checkout: "
                           "`mcp collab seat new <callsign>`" % (wd, d.get("hostname")))
    if callsign:
        if not SEAT_RE.match(callsign):
            return False, ("invalid callsign '%s' — lowercase letters, digits and hyphens "
                           "only, 2-39 chars (underscores break legacy mailbox parsing)"
                           % callsign)
    else:
        host = re.sub(r"[^a-z0-9]+", "-", socket.gethostname().lower()).strip("-") or "host"
        repo = re.sub(r"[^a-z0-9]+", "-", wd.name.lower()).strip("-") or "repo"

        def _reserve(c):
            """The O_EXCL presence stub is the ONLY way a callsign is assigned."""
            try:
                fd = os.open(get_comms_dir() / f"{c}.json",
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, json.dumps(
                    {"hostname": c, "timestamp": _now(), "status": "seating",
                     "current_task": "seat init", "last_seen": time.ctime(),
                     "workdir": str(wd), "session": SESSION, "v": 2},
                    indent=2).encode("utf-8"))
                os.close(fd)
                return True
            except FileExistsError:
                return False

        for n in range(1, 100):
            cand = ("%s-%s-w%d" % (host, repo, n))[:39]
            pres = get_comms_dir() / f"{cand}.json"
            if _reserve(cand):
                callsign = cand
                break
            d = _read_json(pres)
            if not d or (_now() - d.get("timestamp", 0)) < PRESENCE_FRESH_SECONDS:
                continue                           # live reservation — next candidate
            # Idle is not gone: a callsign still BOUND by a seat file in its
            # recorded workdir is taken until that seat is removed.
            wd_rec = d.get("workdir")
            if wd_rec:
                bound = _read_json(Path(wd_rec) / ".mcp" / "seat.json")
                if bound and bound.get("identity") == cand:
                    continue
            tomb, _ = _cas_take(pres)              # atomic reclaim — exactly one winner
            if tomb is None:
                continue
            try:
                tomb.unlink()
            except OSError:
                pass
            if _reserve(cand):                     # back through the same O_EXCL gate
                callsign = cand
                break
        if not callsign:
            return False, "could not allocate a default callsign — pass one explicitly"
    spath.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(spath, "x", encoding="utf-8") as f:      # create-once: NEVER overwritten
            json.dump({"identity": callsign, "workdir": str(wd),
                       "created": _now(), "v": 1}, f, indent=2)
    except FileExistsError:
        cur = _read_json(spath)
        if cur and cur.get("identity") == callsign:
            clear_seat_cache()
            return True, callsign
        return False, ("seat raced: workdir was just seated as '%s'"
                       % (cur or {}).get("identity"))
    clear_seat_cache()
    if wd == Path.cwd().resolve():
        heartbeat(callsign, "active", "seat init", project)
    journal_log(project, callsign, "seat.init", {"workdir": str(wd)})
    return True, callsign


def seat_new(callsign: str, project: str = "default"):
    """Provision a NEW seat: a git worktree at ../<repo>-<callsign> with its own
    .mcp/seat.json. The fastest path from 'I need another agent on this machine'
    to a structurally-safe second seat. Returns (ok, message)."""
    if not callsign or not SEAT_RE.match(callsign):
        return False, ("invalid callsign '%s' — lowercase letters, digits and hyphens only"
                       % callsign)
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, timeout=15, check=True).stdout.strip()
    except Exception as e:
        return False, "not inside a git repository (git rev-parse failed: %s)" % e
    repo_root = Path(top)
    wt = repo_root.parent / ("%s-%s" % (repo_root.name, callsign))
    if wt.exists():
        return False, "worktree path already exists: %s" % wt
    try:
        subprocess.run(["git", "worktree", "add", str(wt)], capture_output=True,
                       text=True, timeout=60, check=True, cwd=str(repo_root))
    except subprocess.CalledProcessError as e:
        return False, "git worktree add failed: %s" % (e.stderr or e.stdout or e)
    except Exception as e:
        return False, "git worktree add failed: %s" % e
    ok, ident = seat_init(callsign, workdir=wt, project=project)
    if not ok:
        return False, ident
    journal_log(project, callsign, "seat.new", {"worktree": str(wt)})
    return True, ("seat '%s' provisioned at %s\n"
                  "  next: cd %s\n"
                  "        python mcp-agentic-rules/mcp.py collab join %s --project %s\n"
                  "  note: worktrees share .git/hooks — this seat is already commit-gated"
                  % (callsign, wt, wt, callsign, project))


def seat_status():
    """Resolved identity, where it came from, and the workdir. Returns lines."""
    env = os.environ.get("AGENT_IDENTITY")
    seat = find_seat_file()
    seat_id = (_read_json(seat) or {}).get("identity") if seat else None
    resolved = env or seat_id or socket.gethostname()
    source = "env:AGENT_IDENTITY" if env else ("seat:%s" % seat if seat_id else "hostname")
    return ["identity: %s" % resolved,
            "source:   %s" % source,
            "workdir:  %s" % Path.cwd(),
            "seat:     %s" % (seat or "(none — run `mcp collab seat init [callsign]`)")]


# ── janitor (bounded store GC — stale state must self-heal) ───────────────────────────────────
def _janitor_sweep(project: str, who: str, dry_run: bool = False):
    """One bounded janitor pass over THIS machine's store. Every deletion is
    rename-CAS-or-tolerant; at most GC_UNLINK_BOUND removals per pass. The
    invariants are per-store: NSync may resurrect reaped files until the
    deletion propagates. Returns a counts dict."""
    counts = {}
    state = {"deleted": 0}

    def reap(path: Path, kind: str):
        if state["deleted"] >= GC_UNLINK_BOUND:
            return False
        if not dry_run:
            tomb, _ = _cas_take(path)
            if tomb is None:
                return False
            try:
                tomb.unlink()
            except OSError:
                pass
        counts[kind] = counts.get(kind, 0) + 1
        state["deleted"] += 1
        return True

    now = _now()
    comms = get_comms_dir()
    base = collab_dir(project)
    live = set()
    for f in comms.glob("*.json"):
        d = _read_json(f)
        if not d or "timestamp" not in d:
            continue
        age = now - d.get("timestamp", 0)
        if age < PRESENCE_FRESH_SECONDS:
            live.add(d.get("hostname", f.stem))
        elif age > GC_PRESENCE_DAYS * 86400:
            reap(f, "presence")
    for f in (base / "claims").glob("*.json"):
        c = _read_json(f)
        if not c:
            continue
        age = now - c.get("time", 0)
        cid = str(c.get("id", ""))
        orphaned = (cid.startswith("issue-")
                    and not (base / "work" / (cid + ".json")).exists()
                    and age > GC_PENDING_MINUTES * 60)
        if (orphaned or age > 24 * 3600) and c.get("owner") not in live:
            if reap(f, "claim_orphaned" if orphaned else "claim_stale") and not dry_run:
                journal_log(project, who, "claim.reaped",
                            {"id": cid, "owner": c.get("owner")})
    for f in (base / "work").glob("issue-*.json"):
        w = _read_json(f)
        if not w:
            continue
        age = now - w.get("started", 0)
        if w.get("phase") == "pending" and age > GC_PENDING_MINUTES * 60:
            if reap(f, "work_pending") and not dry_run:
                claim_drop(project, "issue-%d" % w.get("issue", 0), who)
                journal_log(project, who, "work.reaped_pending",
                            {"issue": w.get("issue"), "owner": w.get("owner")})
        elif age > WORK_STALE_HOURS * 3600 and w.get("owner") not in live:
            if reap(f, "work_stale") and not dry_run:
                journal_log(project, who, "work.reaped",
                            {"issue": w.get("issue"), "owner": w.get("owner")})
    for d in (base, base / "leases", base / "claims", base / "work", comms):
        if not d.is_dir():
            continue
        for pattern in (".*.tmp", ".*.tomb.*"):
            for f in d.glob(pattern):
                try:
                    if now - f.stat().st_mtime > GC_TMP_HOURS * 3600:
                        reap(f, "tmp_stray")
                except OSError:
                    pass
    jdir = base / "journal"
    if jdir.is_dir():
        for f in jdir.glob("*.ndjson"):
            try:
                if now - f.stat().st_mtime > GC_JOURNAL_DAYS * 86400:
                    reap(f, "journal_archive")
            except OSError:
                pass
    for maildir in (comms / "messages", comms / "telegram_inbox", comms / "telegram_outbox"):
        if not maildir.is_dir():
            continue
        for f in maildir.rglob("*.json*"):
            try:
                if f.is_file() and now - f.stat().st_mtime > GC_MAIL_DAYS * 86400:
                    reap(f, "mail")
            except OSError:
                pass
    if (comms / "collab").is_dir():
        for d in (comms / "collab").glob("collab-selftest-*"):
            try:
                if d.is_dir() and now - d.stat().st_mtime > 3600:
                    if not dry_run:
                        shutil.rmtree(d, ignore_errors=True)
                    counts["selftest_scope"] = counts.get("selftest_scope", 0) + 1
            except OSError:
                pass
    if not dry_run:
        atomic_write_json(base / ".last_gc", {"t": now, "by": who, "counts": counts})
        if counts:
            journal_log(project, who, "gc.swept", counts)
    return counts


def _janitor_maybe(project: str, who: str):
    """Opportunistic GC election (called from `status`): at most one janitor per
    600s across all agents, elected via the 'janitor' lease. Crash self-heals
    through the lease TTL."""
    marker = collab_dir(project) / ".last_gc"
    try:
        if marker.exists() and _now() - marker.stat().st_mtime < 600:
            return
    except OSError:
        return
    ok, info = lease_acquire(project, "janitor", who, ttl=120)
    if not ok:
        return
    try:
        _janitor_sweep(project, who)
    finally:
        lease_release(project, "janitor", who, fence=(info or {}).get("fence"))


# ── onboarding (the "you are an additional agent" answer, generic for any project) ────────────
ONBOARD_TEXT = """\
=== HOW TO JOIN A MULTI-AGENT COLLAB TEAM (mcp collab) ===
You were told you're an ADDITIONAL AGENT on a team. Do exactly this:

1. TAKE A SEAT: `mcp collab join <callsign> --project <P>` — it binds THIS workdir to your
   call-sign (.mcp/seat.json), refuses if the workdir is another agent's live seat, verifies
   the engine, and prints the team status. Need a fresh workdir on this machine instead?
   `mcp collab seat new <callsign>` provisions a git worktree seat in one command.
   NEVER share a workdir; never rely on --as alone. One workdir = one agent.
2. READ THE ROOM: `mcp collab status --project <P>` — active agents + their tasks, every
   lease (who is allowed to do what), claims (who owns which source areas), checked-out
   issues + conflict radar, the journal tail. Check your mail: `mcp comms listen`.
3. THE LEASE LAW (typical resources — projects may define more):
   - A lease is EXCLUSIVE while its holder is alive (TTL-renewed). NEVER work around a held
     lease; coordinate via messages/journal instead. Stale leases auto-break — never deadlock.
   - Acquiring prints a FENCE number. Before any irreversible action under a lease, confirm
     you still hold that incarnation: `mcp collab lease valid <res> --fence N`.
   - Common leases: a live tool/editor seat (its holder is the PILOT), build/rebuild rights,
     the git-commit window (same-machine working-tree ops), exclusive test/bench windows.
4. CLAIM before you author: `mcp collab claim add <id> "<path-pattern>" --as <callsign>` —
   and respect existing claims shown in status.
5. UNITS OF WORK are GitHub issues when the project has a remote: `mcp collab work list`
   to see what's open and who holds what, `work start <issue#>` to check one out (it
   assigns + labels the issue and creates your claim), `work done <issue#> [--pr URL]`
   when finished, `work drop <issue#>` to hand it back. Never start an issue another
   agent has checked out — status shows checkouts and the conflict radar.
6. JOURNAL everything material: intents before, results after —
   `mcp collab journal log intent --data '{"text": "..."}'`. Tail it at EVERY loop start.
7. LANDING WORK: every commit is E2E-gated (hooks + CI). Small teams: acquire the
   git-commit lease -> fetch + rebase -> push -> release -> journal the commit hash.
   At scale, work on your issue branch (`work start --branch`) and open a PR.
8. Message any teammate: `mcp comms send <callsign> note "<text>"`; read yours each loop.
Projects may carry their own onboarding (e.g. a repo skill) with project-specific lease names —
that version wins on specifics.
"""


def _selftest_fake_gh(state):
    """Offline gh: a state dict behind the same (ok, out) contract as _gh_real."""
    def fake(gh_args):
        return _fake_gh_apply(state, gh_args)
    return fake


_RACE_SNIPPET = """\
import os, sys, time, json
sys.path.insert(0, os.environ["MCP_PKG_ROOT"])
from scripts import agent_collab as ac
store = os.environ["MCP_NSYNC_PATH"]
go = os.path.join(store, "race-go")
deadline = time.time() + 10
while not os.path.exists(go):
    if time.time() > deadline:
        sys.exit(3)
    time.sleep(0.01)
ok, info = ac.lease_acquire(os.environ["RACE_SCOPE"], "contested",
                            os.environ["AGENT_IDENTITY"], ttl=600)
out = os.path.join(store, "race-res-%s.txt" % os.environ["AGENT_IDENTITY"])
with open(out, "w") as f:  # write-ok: single-writer result file
    f.write("%d:%d" % (int(ok), int((info or {}).get("fence", -1))))
"""


def selftest():
    """Verify the WHOLE engine end-to-end inside a throwaway store (the run sets
    MCP_NSYNC_PATH to a fresh temp dir — 100 agents can run selftest concurrently
    without touching each other or the real store). Returns (ok, lines)."""
    import tempfile
    import threading
    lines = []
    ok = True

    def check(name, cond):
        nonlocal ok
        lines.append(("PASS " if cond else "FAIL ") + name)
        ok = ok and cond

    P = "collab-selftest"
    A, B = "selfA", "selfB"
    saved_env = os.environ.get("MCP_NSYNC_PATH")
    saved_identity = os.environ.get("AGENT_IDENTITY")
    saved_rotate = globals()["JOURNAL_ROTATE_BYTES"]
    saved_cwd = os.getcwd()
    store = tempfile.mkdtemp(prefix="collab-selftest-")
    os.environ["MCP_NSYNC_PATH"] = store
    try:
        # ---- leases: exclusion, staleness, fencing, corruption, refusal ----
        a_ok, _ = lease_acquire(P, "seat", A, ttl=600)
        b_ok, b_info = lease_acquire(P, "seat", B, ttl=600)
        a_again, _ = lease_acquire(P, "seat", A, ttl=600)
        rel_b, _ = lease_release(P, "seat", B)
        check("lease exclusion + re-entrancy + foreign-release refusal",
              a_ok and not b_ok and b_info.get("owner") == A and a_again and not rel_b)
        lease_release(P, "seat", A)
        lease_acquire(P, "seat", A, ttl=0.5)
        time.sleep(0.8)
        b2_ok, _ = lease_acquire(P, "seat", B, ttl=600)
        check("stale lease auto-break", b2_ok and lease_info(P, "seat")["owner"] == B)
        lease_release(P, "seat", B)

        ok1, l1 = lease_acquire(P, "fenced", A, ttl=600)
        lease_release(P, "fenced", A, fence=l1.get("fence"))
        ok2, l2 = lease_acquire(P, "fenced", B, ttl=0.4)
        time.sleep(0.6)
        ok3, l3 = lease_acquire(P, "fenced", A, ttl=600)
        check("fence strictly increases across transitions (sidecar continuity)",
              ok1 and ok2 and ok3
              and (l1["fence"], l2["fence"], l3["fence"]) == (1, 2, 3))
        rn_ok, rn_info = lease_renew(P, "fenced", A, fence=2)
        check("renew with a superseded fence is refused loudly",
              not rn_ok and "refusal" in (rn_info or {}))
        v_ok, _ = lease_valid(P, "fenced", A, l3["fence"])
        lease_release(P, "fenced", A, fence=l3["fence"])
        v2_ok, _ = lease_valid(P, "fenced", A, l3["fence"])
        check("lease_valid tracks the live incarnation", v_ok and not v2_ok)

        backdated = _now() - CORRUPT_GRACE_SECONDS - 5
        lease_path(P, "rusty").write_text("NOT JSON AT ALL", encoding="utf-8")  # write-ok: corrupt fixture
        os.utime(lease_path(P, "rusty"), (backdated, backdated))
        cr_ok, cr_info = lease_acquire(P, "rusty", A, ttl=600)
        check("corrupt lease is auto-broken, then acquirable",
              cr_ok and cr_info.get("owner") == A and cr_info.get("fence", 0) >= 1)
        lease_release(P, "rusty", A)
        lease_path(P, "rusty2").write_text("{torn", encoding="utf-8")  # write-ok: corrupt fixture
        os.utime(lease_path(P, "rusty2"), (backdated, backdated))
        br_ok, _ = lease_break(P, "rusty2", A)
        check("lease break clears a corrupt file (no permanent deadlock)",
              br_ok and not lease_path(P, "rusty2").exists())
        lease_path(P, "youngling").write_text("{mid-write", encoding="utf-8")  # write-ok: corrupt fixture
        yb_ok, _ = lease_break(P, "youngling", A)
        check("young unparseable lease is NOT treated as corrupt (mid-write grace)",
              not yb_ok and lease_path(P, "youngling").exists())
        lease_path(P, "youngling").unlink()

        atomic_write_json(lease_path(P, "remote"),
                          {"resource": "remote", "owner": A, "workdir": "Z:/elsewhere",
                           "session": "x", "acquired": _now(), "renewed": _now(),
                           "ttl": 600, "note": "", "fence": 9, "v": 2})
        wr_ok, wr_info = lease_acquire(P, "remote", A, ttl=600)
        check("cross-workdir same-identity acquisition is REFUSED",
              not wr_ok and "refusal" in (wr_info or {}))

        # adversarial-review hardening: renew can never resurrect or clobber
        h_ok, lh = lease_acquire(P, "hardened", A, ttl=0.4)
        time.sleep(0.6)
        hr_ok, hr = lease_renew(P, "hardened", A)
        check("renew refuses to resurrect an expired lease",
              h_ok and not hr_ok and "refusal" in (hr or {}))
        ra_ok, ra = lease_acquire(P, "hardened", A, ttl=600)
        check("re-acquiring your own expired lease mints a HIGHER fence",
              ra_ok and ra["fence"] == lh["fence"] + 1)
        _fence_path(P, "hardened").unlink()        # simulate a crashed sidecar bump
        lease_release(P, "hardened", A, fence=ra["fence"])
        cw_ok, cw = lease_acquire(P, "hardened", B, ttl=600)
        check("retirement preserves the fence high-water mark (crash window closed)",
              cw_ok and cw["fence"] > ra["fence"])
        lease_release(P, "hardened", B, fence=cw["fence"])

        # ---- atomic visibility under concurrent rewrite ----
        target = Path(store) / "atomic-probe.json"
        atomic_write_json(target, {"i": -1})
        writer_err = []

        def _writer():
            try:
                for i in range(300):
                    atomic_write_json(target, {"i": i})
            except Exception as e:                       # pragma: no cover
                writer_err.append(e)
        th = threading.Thread(target=_writer)
        th.start()
        torn = 0
        for _ in range(300):
            if _read_json(target) is None:
                torn += 1
        th.join()
        check("atomic visibility: no torn reads under concurrent rewrite",
              torn == 0 and not writer_err)

        # ---- journal: order, segments, rotation, corruption tolerance ----
        journal_log(P, A, "t.one", {"n": 1})
        time.sleep(0.002)
        journal_log(P, B, "t.two", {"n": 2})
        evs = [(e["who"], e["event"]) for e in journal_tail(P, 50)]
        check("journal order across writer segments",
              (A, "t.one") in evs and (B, "t.two") in evs
              and evs.index((A, "t.one")) < evs.index((B, "t.two")))
        for i in range(30):
            journal_log(P, A if i % 2 else B, "bulk.%d" % i, {"i": i})
        tail = journal_tail(P, 100)
        ts = [e.get("t", 0) for e in tail]
        check("merged tail is complete and time-ordered",
              sum(1 for e in tail if e["event"].startswith("bulk.")) == 30
              and ts == sorted(ts))
        globals()["JOURNAL_ROTATE_BYTES"] = 200
        for i in range(5):
            journal_log(P, A, "rot.%d" % i, {"pad": "x" * 60})
        globals()["JOURNAL_ROTATE_BYTES"] = saved_rotate
        seg_count = len(list((collab_dir(P) / "journal").glob("*.ndjson")))
        check("rotation leaves archives + events readable",
              seg_count >= 3 and any(e["event"] == "rot.4" for e in journal_tail(P, 50)))
        seg = next(iter((collab_dir(P) / "journal").glob("%s.*.ndjson" % A)))
        with open(seg, "a", encoding="utf-8") as f:
            f.write("GARBAGE NOT JSON\n")
        check("corrupt journal line is skipped without error",
              any(e["event"] == "rot.4" for e in journal_tail(P, 50)))

        # ---- claims ----
        c_ok, _ = claim_add(P, "area", "src/*", A)
        c2_ok, c2 = claim_add(P, "area", "src/x", B)
        d_ok, _ = claim_drop(P, "area", A)
        check("claim conflict + drop", c_ok and not c2_ok and c2.get("owner") == A and d_ok)
        _claim_path(P, "rusty-claim").write_text("]not json[", encoding="utf-8")  # write-ok: corrupt fixture
        os.utime(_claim_path(P, "rusty-claim"), (backdated, backdated))
        cc_ok, _ = claim_add(P, "rusty-claim", "y/*", A)
        check("corrupt claim self-heals then is claimable", cc_ok)
        claim_drop(P, "rusty-claim", A)
        cf_ok, cf1 = claim_add(P, "refresh-area", "a/*", A)
        cf2_ok, cf2 = claim_add(P, "refresh-area", "b/*", A)     # owner refresh (CAS)
        check("claim refresh keeps ownership + original time, updates pattern",
              cf_ok and cf2_ok and cf2["pattern"] == "b/*" and cf2["time"] == cf1["time"])
        claim_drop(P, "refresh-area", A)

        # ---- wait-acquire ----
        lease_acquire(P, "waitres", A, ttl=0.5)
        t0 = time.time()
        got = False
        while time.time() - t0 < 5.0:                    # --wait semantics, inlined
            okw, _ = lease_acquire(P, "waitres", B, ttl=600)
            if okw:
                got = True
                break
            time.sleep(0.3)
        check("wait-acquire over an expiring lease", got)
        lease_release(P, "waitres", B)

        # ---- presence + collision detector (evidence-gated) ----
        pay, warn = heartbeat("selfC", "active", "selftest", P)
        check("heartbeat carries workdir + session",
              pay.get("workdir") == str(Path.cwd()) and pay.get("session") == SESSION
              and warn is None)
        pfile = get_comms_dir() / "selfD.json"
        atomic_write_json(pfile, {"hostname": "selfD", "timestamp": _now() - 60,
                                  "workdir": str(Path.cwd()), "session": "zzz", "v": 2})
        _, w1 = heartbeat("selfD", "active", "restart", P)
        atomic_write_json(pfile, {"hostname": "selfD", "timestamp": _now() - 2,
                                  "workdir": str(Path.cwd()), "session": "zzz", "v": 2})
        _, w2 = heartbeat("selfD", "active", "concurrent", P)
        atomic_write_json(pfile, {"hostname": "selfD", "timestamp": _now() - 2,
                                  "workdir": "/somewhere/else", "session": "zzz", "v": 2})
        _, w3 = heartbeat("selfD", "active", "crossdir", P)
        check("collision detector: restart quiet, concurrency loud, cross-workdir loud",
              w1 is None and w2 is not None and w3 is not None)

        # ---- work lifecycle over the fake gh ----
        state = {"issues": {
            "7": {"title": "Wire the flux capacitor", "url": "https://github.com/x/y/issues/7",
                  "body": "Touch src/flux.py and docs/flux.md\n- [ ] wire it\n- [ ] test it",
                  "labels": [], "state": "open"},
            "9": {"title": "Polish the flux capacitor", "url": "https://github.com/x/y/issues/9",
                  "body": "Also edits src/flux.py", "labels": [], "state": "open"},
            "11": {"title": "Rollback probe", "url": "https://github.com/x/y/issues/11",
                   "body": "Edits src/rb.py", "labels": [], "state": "open"},
            "12": {"title": "Foreign checkout", "url": "https://github.com/x/y/issues/12",
                   "body": "Edits src/far.py", "labels": ["in-progress", "agent:zz"],
                   "state": "open"},
        }}
        fake = _selftest_fake_gh(state)
        s_ok, _ = work_start(P, 7, A, runner=fake)
        claims = {c["id"]: c for c in claims_all(P)}
        rec = _read_json(work_path(P, 7))
        tail_evs = [e["event"] for e in journal_tail(P, 10)]
        check("work start = labels + claim(url in note) + active record + journal",
              s_ok and "in-progress" in state["issues"]["7"]["labels"]
              and "agent:selfA" in state["issues"]["7"]["labels"]
              and "issue-7" in claims and "issues/7" in claims["issue-7"]["note"]
              and "src/flux.py" in claims["issue-7"]["pattern"]
              and rec is not None and rec.get("owner") == A
              and rec.get("phase") == "active" and "work.start" in tail_evs)
        wb_ok, wb_msg = work_start(P, 7, B, runner=fake)
        check("work checkout exclusivity", not wb_ok and A in wb_msg)
        r_ok, r_msg = work_start(P, 9, B, runner=fake)
        radar = work_conflicts(P)
        check("conflict radar flags overlapping checkouts",
              r_ok and "CONFLICT RADAR" in r_msg
              and any({pair[0], pair[2]} == {7, 9} for pair in radar))
        t_ok, _ = work_tick(P, 7, 1, A, runner=fake)
        check("work tick flips the checkbox",
              t_ok and "- [x] wire it" in state["issues"]["7"]["body"]
              and "- [ ] test it" in state["issues"]["7"]["body"])
        d_ok, _ = work_done(P, 7, A, runner=fake)
        check("work done closes + releases claim + record",
              d_ok and state["issues"]["7"]["state"] == "closed"
              and "issue-7" not in {c["id"] for c in claims_all(P)}
              and not work_path(P, 7).exists())
        work_drop(P, 9, B, runner=fake)
        g_ok, g_msg = work_start(P, 12, A, runner=fake)
        check("label guard refuses a foreign GitHub-side checkout",
              not g_ok and "in-progress" in g_msg
              and "issue-12" not in {c["id"] for c in claims_all(P)})
        state["fail_edit"] = True
        rb_ok, _ = work_start(P, 11, A, runner=fake)
        state["fail_edit"] = False
        check("hard gh failure rolls the checkout back (no divergence)",
              not rb_ok and not work_path(P, 11).exists()
              and "issue-11" not in {c["id"] for c in claims_all(P)}
              and any(e["event"] == "work.rolled_back" for e in journal_tail(P, 10)))
        state["offline"] = True
        o_ok, o_msg = work_start(P, 7, A, runner=fake)
        state["offline"] = False
        check("work degrades clearly without gh",
              not o_ok and "gh" in o_msg.lower() and not work_path(P, 7).exists()
              and "issue-7" not in {c["id"] for c in claims_all(P)})

        # ---- seats ----
        wd1 = Path(tempfile.mkdtemp(prefix="seat1-", dir=store))
        s1_ok, s1 = seat_init("tst-alpha", workdir=wd1, project=P)
        s1b_ok, _ = seat_init("tst-alpha", workdir=wd1, project=P)
        s1c_ok, s1c = seat_init("tst-beta", workdir=wd1, project=P)
        su_ok, su = seat_init("bad_name", workdir=Path(tempfile.mkdtemp(dir=store)), project=P)
        check("seat: create-once, idempotent re-init, second callsign refused, charset",
              s1_ok and s1 == "tst-alpha" and s1b_ok and not s1c_ok and not su_ok
              and "underscore" in su)
        wd3 = Path(tempfile.mkdtemp(prefix="seat3-", dir=store)).resolve()
        atomic_write_json(get_comms_dir() / "occupier.json",
                          {"hostname": "occupier", "timestamp": _now(),
                           "workdir": str(wd3), "session": "q", "v": 2})
        s3_ok, s3 = seat_init("newbie", workdir=wd3, project=P)
        check("seat refuses a workdir that is another agent's live seat",
              not s3_ok and "occupier" in s3)
        wd4 = Path(tempfile.mkdtemp(prefix="seat4-", dir=store))
        s4_ok, s4 = seat_init(None, workdir=wd4, project=P)
        check("default callsign allocation is collision-free and well-formed",
              s4_ok and re.match(r"^[a-z0-9][a-z0-9-]*-w\d+$", s4 or ""))
        # same-basename workdirs collide on candidate names — the hard cases:
        pa = Path(tempfile.mkdtemp(dir=store)) / "samename"
        pb = Path(tempfile.mkdtemp(dir=store)) / "samename"
        pc = Path(tempfile.mkdtemp(dir=store)) / "samename"
        pa.mkdir(); pb.mkdir(); pc.mkdir()
        sa_ok, sa = seat_init(None, workdir=pa, project=P)
        presa = get_comms_dir() / (str(sa) + ".json")
        da = _read_json(presa)
        da["timestamp"] = _now() - 3600                    # idle, but still SEATED
        atomic_write_json(presa, da)
        sb_ok, sb = seat_init(None, workdir=pb, project=P)
        check("an idle seat-bound callsign is never auto-reused",
              sa_ok and sb_ok and sb != sa)
        presb = get_comms_dir() / (str(sb) + ".json")
        db = _read_json(presb)
        db["timestamp"] = _now() - 3600
        atomic_write_json(presb, db)
        (pb / ".mcp" / "seat.json").unlink()               # agent gone for good
        sc_ok, sc = seat_init(None, workdir=pc, project=P)
        check("a stale UNBOUND reservation is reclaimed atomically",
              sc_ok and sc == sb)
        if saved_identity:
            os.environ.pop("AGENT_IDENTITY", None)
        clear_seat_cache()
        os.chdir(wd1)
        resolved = get_hostname()
        os.chdir(saved_cwd)
        clear_seat_cache()
        if saved_identity:
            os.environ["AGENT_IDENTITY"] = saved_identity
        check("identity resolves from the workdir seat file", resolved == "tst-alpha")

        # ---- janitor gc ----
        old = _now() - 8 * 86400
        atomic_write_json(get_comms_dir() / "ghostpresence.json",
                          {"hostname": "ghostpresence", "timestamp": old, "workdir": "x"})
        claim_add(P, "dead-area", "x/*", "ghost1")
        cpath = _claim_path(P, "dead-area")
        cdata = _read_json(cpath)
        cdata["time"] = _now() - 25 * 3600
        atomic_write_json(cpath, cdata)
        claim_add(P, "issue-99", "y/*", "ghost2")
        cpath99 = _claim_path(P, "issue-99")
        cdata99 = _read_json(cpath99)
        cdata99["time"] = _now() - 11 * 60
        atomic_write_json(cpath99, cdata99)
        atomic_write_json(work_path(P, 98),
                          {"issue": 98, "owner": "ghost3", "phase": "active",
                           "started": _now() - 25 * 3600, "v": 2})
        atomic_write_json(work_path(P, 97),
                          {"issue": 97, "owner": "ghost4", "phase": "pending",
                           "started": _now() - 11 * 60, "v": 2})
        stray = collab_dir(P) / ".stray.json.123.tmp"
        stray.write_text("x", encoding="utf-8")  # write-ok: gc fixture
        os.utime(stray, (old, old))
        claim_add(P, "fresh-area", "z/*", A)
        counts = _janitor_sweep(P, A)
        check("janitor reaps presence/claims/work/pending/strays, keeps fresh",
              counts.get("presence", 0) >= 1 and counts.get("claim_stale", 0) >= 1
              and counts.get("claim_orphaned", 0) >= 1 and counts.get("work_stale", 0) >= 1
              and counts.get("work_pending", 0) >= 1 and counts.get("tmp_stray", 0) >= 1
              and _claim_path(P, "fresh-area").exists())
        claim_drop(P, "fresh-area", A)

        # ---- mailbox exact delivery ----
        from scripts import agent_comms
        agent_comms.send_message("mt-a", "note", {"text": "one"}, sender="mt-b")
        agent_comms.send_message("mt-a", "note", {"text": "two"}, sender="mt-b")
        legacy_mine = get_comms_dir() / "messages" / "mt-a_mt-b_111.json"
        legacy_mine.write_text(json.dumps(            # write-ok: legacy fixture
            {"to": "mt-a", "from": "mt-b", "type": "note",
             "content": {"text": "legacy"}}), encoding="utf-8")
        legacy_steal = get_comms_dir() / "messages" / "mt-a_q_mt-c_5.json"
        legacy_steal.write_text(json.dumps(           # write-ok: legacy fixture
            {"to": "mt-a_q", "from": "mt-c", "type": "note",
             "content": {"text": "not yours"}}), encoding="utf-8")
        got_msgs = agent_comms.listen_for_messages(identity="mt-a")
        texts = sorted(m["content"]["text"] for m in got_msgs)
        check("mailbox: same-ms safe, legacy read, prefix-steal prevented",
              texts == ["legacy", "one", "two"] and legacy_steal.exists())
        for i in range(6):
            agent_comms.send_message("mt-c2", "note", {"text": "m%d" % i}, sender="mt-b")
        bucket = []

        def _consume():
            bucket.extend(agent_comms.listen_for_messages(identity="mt-c2"))
        t1, t2 = threading.Thread(target=_consume), threading.Thread(target=_consume)
        t1.start(); t2.start(); t1.join(); t2.join()
        check("mailbox: concurrent consumers see each message exactly once",
              sorted(m["content"]["text"] for m in bucket) == ["m%d" % i for i in range(6)])

        # ---- race smoke: real processes contending for one stale lease ----
        atomic_write_json(lease_path(P, "contested"),
                          {"resource": "contested", "owner": "dead", "acquired": 0,
                           "renewed": 0, "ttl": 0.1, "fence": 5, "v": 2})
        _fence_bump(P, "contested", 5)
        procs = []
        spawn_ok = True
        try:
            for i in range(4):
                env = {**os.environ,
                       "MCP_NSYNC_PATH": store,
                       "MCP_PKG_ROOT": str(Path(__file__).resolve().parents[1]),
                       "AGENT_IDENTITY": "racer-%d" % i,
                       "RACE_SCOPE": P}
                procs.append(subprocess.Popen([sys.executable, "-c", _RACE_SNIPPET],
                                              env=env, cwd=str(Path(__file__).parents[1])))
        except OSError:
            spawn_ok = False
        if spawn_ok:
            (Path(store) / "race-go").write_text("go", encoding="utf-8")  # write-ok: barrier flag
            for p in procs:
                try:
                    p.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    p.kill()
                    spawn_ok = False
        if spawn_ok:
            results = []
            for i in range(4):
                rf = Path(store) / ("race-res-racer-%d.txt" % i)
                results.append(rf.read_text(encoding="utf-8") if rf.exists() else "?")
            winners = [r for r in results if r.startswith("1:")]
            check("race smoke: exactly one winner across processes, fence advanced",
                  len(winners) == 1 and winners[0] == "1:6" and len(results) == 4)
        else:
            lines.append("SKIP race smoke (subprocess spawn unavailable)")
    finally:
        if saved_env is None:
            os.environ.pop("MCP_NSYNC_PATH", None)
        else:
            os.environ["MCP_NSYNC_PATH"] = saved_env
        globals()["JOURNAL_ROTATE_BYTES"] = saved_rotate
        os.chdir(saved_cwd)
        clear_seat_cache()
        shutil.rmtree(store, ignore_errors=True)
    return ok, lines


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────
def _status_lines(project: str, who: str):
    """The one-view status body (shared by `status` and `join`)."""
    lines = ["", "-- agents (presence) --"]
    for f in sorted(get_comms_dir().glob("*.json")):
        d = _read_json(f)
        if not d or "timestamp" not in d:
            continue
        age = _now() - d.get("timestamp", 0)
        mark = "ACTIVE" if age < PRESENCE_FRESH_SECONDS else "stale"
        wd = d.get("workdir", "?")
        lines.append(f"  {f.stem:<20} [{mark:>6}] {d.get('current_task', '?')[:50]}"
                     f"  ({int(age)}s ago)  @{wd}")
    lines += ["", "-- leases --"]
    all_leases = leases_all(project)
    if not all_leases:
        lines.append("  (all free)")
    for name, info in sorted(all_leases.items()):
        state = "STALE" if info["stale"] else f"{int(info['expires_in'])}s left"
        lines.append(f"  {name:<14} held by {info['owner']} (fence={info.get('fence', '?')}, "
                     f"{state})  {info.get('note', '')}")
    lines += ["", "-- claims --"]
    cs = claims_all(project)
    if not cs:
        lines.append("  (none)")
    for c in cs:
        lines.append(f"  {c['id']:<20} {c['pattern']}  (owner {c['owner']})")
    lines += ["", "-- work (gh issues checked out) --"]
    ws = work_all(project)
    if not ws:
        lines.append("  (none)")
    for w in ws:
        b = f" branch={w['branch']}" if w.get("branch") else ""
        lines.append(f"  #{w['issue']:<5} {w.get('title', '')[:48]}  (owner {w['owner']}{b})")
    for ia, oa, ib, ob, ov in work_conflicts(project):
        lines.append(f"  [CONFLICT RADAR] #{ia} ({oa}) and #{ib} ({ob}) "
                     f"both touch: {', '.join(ov[:5])}")
    lines += ["", "-- journal (last 10) --"]
    for e in journal_tail(project, 10):
        lines.append(f"  {e['ts']}  {e['who']:<16} {e['event']:<20} "
                     f"{json.dumps(e['data'], ensure_ascii=False)[:100]}")
    return lines


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
        fence_opt = _pop_opt(args, "--fence")
        fence = int(fence_opt) if fence_opt is not None else None
        if verb == "valid":
            ok, info = lease_valid(project, resource, who, fence or 0)
            print("[OK] holding %s (fence=%s)" % (resource, fence)
                  if ok else "[LOST] %s — stop work and re-acquire" % resource)
            return 0 if ok else 1
        fn = {"acquire": lambda: lease_acquire(project, resource, who, ttl, note),
              "release": lambda: lease_release(project, resource, who, fence),
              "renew": lambda: lease_renew(project, resource, who, fence),
              "break": lambda: lease_break(project, resource, who)}.get(verb)
        if not fn:
            print(f"[FAIL] unknown lease verb: {verb}")
            return 1
        ok, info = fn()
        if not ok and verb == "acquire" and wait_s > 0:
            deadline = time.time() + wait_s
            attempt = 0
            while not ok and time.time() < deadline:   # jittered poll — no thundering herd
                _backoff_sleep(attempt, base=0.5, cap=min(15.0, max(2.0, wait_s / 4)))
                attempt += 1
                ok, info = fn()
        if ok:
            if verb == "acquire":
                print(f"[OK] acquire {resource} ({who}) fence={int((info or {}).get('fence', 0))}")
            else:
                print(f"[OK] {verb} {resource} ({who})")
            return 0
        if info and info.get("refusal"):
            print("[REFUSED] " + info["refusal"])
            return 1
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

    if cmd == "work":
        make_branch = False
        if "--branch" in args:
            args.remove("--branch")
            make_branch = True
        pr = _pop_opt(args, "--pr", "")
        verb = args[1] if len(args) > 1 else "list"
        try:
            if verb == "list":
                ok, out = work_list(project, who)
            elif verb == "start" and len(args) >= 3:
                ok, out = work_start(project, args[2], who, make_branch)
            elif verb == "done" and len(args) >= 3:
                ok, out = work_done(project, args[2], who, pr)
            elif verb == "drop" and len(args) >= 3:
                ok, out = work_drop(project, args[2], who)
            elif verb == "tick" and len(args) >= 4:
                ok, out = work_tick(project, args[2], args[3], who)
            else:
                print("[FAIL] work list | start <issue#> [--branch] | done <issue#> "
                      "[--pr URL] | drop <issue#> | tick <issue#> <item#>")
                return 1
        except ValueError:
            print("[FAIL] issue/item must be numbers")
            return 1
        print(("[OK] " if ok else "[FAIL] ") + out)
        return 0 if ok else 1

    if cmd == "seat":
        verb = args[1] if len(args) > 1 else "status"
        if verb == "status":
            for line in seat_status():
                print(line)
            return 0
        if verb == "init":
            ok, out = seat_init(args[2] if len(args) > 2 else None, project=project)
            print(("[OK] seated as '%s' — identity now resolves from this workdir" % out)
                  if ok else "[REFUSED] " + out)
            return 0 if ok else 1
        if verb == "new" and len(args) > 2:
            ok, out = seat_new(args[2], project=project)
            print(("[OK] " + out) if ok else "[FAIL] " + out)
            return 0 if ok else 1
        print("[FAIL] seat init [callsign] | new <callsign> | status")
        return 1

    if cmd == "join":
        callsign = args[1] if len(args) > 1 else None
        no_verify = "--no-verify" in args
        ok, ident = seat_init(callsign, project=project)
        if not ok:
            print("[REFUSED] " + ident)
            return 1
        heartbeat(ident, "active", "joining the team", project)
        journal_log(project, ident, "agent.join", {"workdir": str(Path.cwd())})
        if not no_verify:
            import tempfile
            probe_store = tempfile.mkdtemp(prefix="collab-join-probe-")
            try:
                proc = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "selftest"],
                    capture_output=True, text=True, timeout=300,
                    env={**os.environ, "MCP_NSYNC_PATH": probe_store})
                if "COLLAB_ENGINE_OK" not in (proc.stdout or ""):
                    print(proc.stdout)
                    print("[FAIL] engine probe failed — fix before collaborating")
                    return 1
                print("[OK] engine probe: COLLAB_ENGINE_OK")
            finally:
                shutil.rmtree(probe_store, ignore_errors=True)
        print(f"=== {project} status ===")
        _janitor_maybe(project, ident)
        for line in _status_lines(project, ident):
            print(line)
        print(f"READY — you are '{ident}'. Journal your intent, claim your area, then work.")
        return 0

    if cmd == "gc":
        counts = _janitor_sweep(project, who, dry_run="--dry-run" in args)
        mode = "would reap" if "--dry-run" in args else "reaped"
        print("[OK] gc %s: %s" % (mode, counts or "nothing"))
        return 0

    if cmd == "swarmtest":
        try:
            from scripts import collab_swarm
        except ImportError:
            from . import collab_swarm
        report = collab_swarm.run_swarm(
            store=_pop_opt(args, "--store"),
            agents=int(_pop_opt(args, "--agents", 8)),
            iters=int(_pop_opt(args, "--iters", 25)),
            ttl=float(_pop_opt(args, "--ttl", 600)),
            hammer="--hammer" in args,
            keep="--keep" in args)
        if "--json" in args:
            print(json.dumps(report, indent=2))
        else:
            for c in report["checks"]:
                print(("PASS " if c["ok"] else "FAIL ") + c["name"]
                      + ("" if c["ok"] else "   [%s]" % c.get("detail", "")))
            print("agents=%d iters=%d hammer=%s elapsed=%.1fs store=%s"
                  % (report["agents"], report["iters"], report["hammer"],
                     report["elapsed"], report["store"]))
        print("COLLAB_SWARM_OK" if report["ok"] else "COLLAB_SWARM_FAIL")
        return 0 if report["ok"] else 1

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
        _janitor_maybe(project, who)
        print(f"=== {project} collaboration status (you are: {who}) ===")
        if warn:
            print("[WARN] " + warn)
        for line in _status_lines(project, who):
            print(line)
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())

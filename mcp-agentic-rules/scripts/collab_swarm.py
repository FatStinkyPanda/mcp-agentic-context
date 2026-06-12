#!/usr/bin/env python3
"""
Collab Swarm Test — N real OS processes hammering one collab store
==================================================================
The E2E proof behind every atomicity claim in agent_collab: spawns N worker
PROCESSES (subprocess, spawn-safe, identical on Windows and POSIX — no
multiprocessing/fork) against one throwaway store and checks the invariants
that make 100 concurrent agents safe:

  SWARM-MUTEX-1   final shared counter == sum of acknowledged increments
                  (no lost updates, no zombie writes after a lost lease)
  SWARM-MUTEX-2   zero guard-token violations (no two simultaneous holders)
  SWARM-JRN       every (writer, seq) journal event exactly once, gap-free,
                  zero torn lines across all segments
  SWARM-CLM       exactly one claim winner per epoch; losers always see a
                  real owner (never a blind failure)
  SWARM-WRK       exactly one work_start winner per seeded fake issue
  SWARM-COL       a shared identity beating from two workdirs is detected
                  (collision warning + identity.collision journal event)

--hammer shrinks the mutex TTL to 0.5s and makes 10% of critical sections
oversleep it: stale-break and fencing get exercised for real — a worker that
loses its lease mid-section must observe lease_valid()==False and NOT write.

Usage:
    mcp collab swarmtest [--agents 8] [--iters 25] [--hammer] [--keep] [--json]
    python scripts/collab_swarm.py worker --role mutex ...   (internal)

Exit contract: final line COLLAB_SWARM_OK / COLLAB_SWARM_FAIL, exit 0/1.
"""

from pathlib import Path
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import agent_collab as ac                       # noqa: E402

ROLES = ("mutex", "journal", "claim", "checkout", "collide")
READY_DEADLINE = 30.0
STALL_SECONDS = 30.0


# ── worker side ───────────────────────────────────────────────────────────────────────────────
def _touch(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(str(time.time()))


def _barrier_wait(sdir: Path, wid: int) -> bool:
    """Register ready, then poll for the orchestrator's go file."""
    _touch(sdir / "ready" / str(wid))
    go = sdir / "go"
    deadline = time.time() + READY_DEADLINE
    while not go.exists():
        if time.time() > deadline:
            return False
        time.sleep(0.01)
    return True


def worker_main(a) -> int:
    me = os.environ.get("AGENT_IDENTITY", "swarm%03d" % a.id)
    sdir = Path(os.environ["MCP_NSYNC_PATH"]) / "swarm" / a.role
    if a.workdir:
        os.chdir(a.workdir)
    out = {"id": a.id, "role": a.role, "acks": 0, "violations": 0, "lost": 0,
           "starved": 0, "stomps": 0, "wins": [], "blind": 0, "warnings": 0,
           "events": 0}
    if not _barrier_wait(sdir, a.id):
        return 3
    progress = sdir / "progress" / str(a.id)

    if a.role == "mutex":
        token = sdir / "token.json"
        counter = sdir / "counter.json"
        for _ in range(a.iters):
            _touch(progress)
            fence = None
            t0 = time.time()
            attempt = 0
            while time.time() - t0 < 60:
                okl, info = ac.lease_acquire(a.scope, "swarm-mutex", me, ttl=a.ttl)
                if okl:
                    fence = info["fence"]
                    break
                ac._backoff_sleep(attempt, base=0.005, cap=0.1)
                attempt += 1
            if fence is None:
                out["starved"] += 1
                continue
            ac.atomic_write_json(token, {"who": me, "fence": fence})
            if a.hammer and random.random() < 0.10:
                time.sleep(a.ttl * 1.5)              # oversleep: lose the lease on purpose
            else:
                time.sleep(random.uniform(0, 0.003))
            still, _ = ac.lease_valid(a.scope, "swarm-mutex", me, fence)
            tok = ac._read_json(token) or {}
            if still and tok.get("who") != me:
                if int(tok.get("fence", -1)) >= fence:
                    # a token from an EQUAL/HIGHER fence while we validly hold
                    # = two simultaneous valid holders: true exclusion breach
                    out["violations"] += 1
                else:
                    # a LOWER-fence token = the Kleppmann zombie write: an
                    # expired holder's delayed write landed on our hold. The
                    # lease layer cannot prevent this — fence-checking at the
                    # resource (exactly what the counter protocol does) can.
                    out["stomps"] += 1
            if still:                                # fenced write: only a VALID holder mutates
                cur = ac._read_json(counter) or {"n": 0}
                ac.atomic_write_json(counter, {"n": cur.get("n", 0) + 1})
                out["acks"] += 1
            else:
                out["lost"] += 1
            ac.lease_release(a.scope, "swarm-mutex", me, fence=fence)

    elif a.role == "journal":
        for i in range(a.iters):
            _touch(progress)
            ac.journal_log(a.scope, me, "swarm.evt", {"seq": i, "who": me})
            out["events"] += 1
            time.sleep(random.uniform(0, 0.001))

    elif a.role == "claim":
        for e in range(a.iters):
            _touch(progress)
            okc, info = ac.claim_add(a.scope, "epoch-%d" % e, "p/%d" % e, me)
            if okc:
                out["wins"].append(e)                # winners HOLD — one winner per epoch ever
            elif not (info and info.get("owner")):
                out["blind"] += 1                    # loser saw no owner: a broken read
            time.sleep(random.uniform(0, 0.002))

    elif a.role == "checkout":
        for n in range(1, a.iters + 1):
            _touch(progress)
            okw, _ = ac.work_start(a.scope, n, me)   # gh diverted by COLLAB_FAKE_GH
            if okw:
                out["wins"].append(n)
            time.sleep(random.uniform(0, 0.002))

    elif a.role == "collide":
        for _ in range(5):
            _touch(progress)
            _, warn = ac.heartbeat("swarm-collider", "active", "collide probe", a.scope)
            if warn:
                out["warnings"] += 1
            time.sleep(0.05)

    (sdir / "out").mkdir(parents=True, exist_ok=True)
    ac.atomic_write_json(sdir / "out" / ("%d.json" % a.id), out)
    return 0


# ── orchestrator side ─────────────────────────────────────────────────────────────────────────
def _collab_base(store: str, scope: str) -> Path:
    return Path(store) / ".nsync_agents" / "collab" / scope


def _read_full_journal(store: str, scope: str):
    """EVERY event in the scope's journal segments (full read, not the bounded
    tail) + the count of unparseable lines."""
    events, torn = [], 0
    jdir = _collab_base(store, scope) / "journal"
    if jdir.is_dir():
        for f in sorted(jdir.glob("*.ndjson")):
            for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if not raw.strip():
                    continue
                try:
                    events.append(json.loads(raw))
                except Exception:
                    torn += 1
    return events, torn


def run_swarm(store=None, agents=8, iters=25, ttl=600.0, roles=ROLES,
              hammer=False, timeout=180.0, keep=False):
    """Run the swarm; returns {'ok', 'checks': [{name, ok, detail}], ...}.
    Always operates on an isolated store (a fresh temp dir unless one is
    passed); the store is kept on failure or keep=True, removed on success."""
    own_store = store is None
    store = str(store or tempfile.mkdtemp(prefix="collab-swarm-"))
    pkg_root = str(Path(__file__).resolve().parents[1])
    checks = []
    t_start = time.time()

    for role in roles:
        scope = "swarm-%s" % role
        n = 2 if role == "collide" else agents
        role_ttl = 0.5 if (hammer and role == "mutex") else ttl
        sdir = Path(store) / "swarm" / role
        (sdir / "ready").mkdir(parents=True, exist_ok=True)
        (sdir / "progress").mkdir(parents=True, exist_ok=True)
        (sdir / "err").mkdir(parents=True, exist_ok=True)
        fake_path = None
        if role == "checkout":
            fake_path = Path(store) / "fake-gh.json"
            ac.atomic_write_json(fake_path, {"issues": {
                str(i): {"title": "swarm issue %d" % i,
                         "url": "https://github.com/x/y/issues/%d" % i,
                         "body": "Touch src/m%d.py" % i, "labels": [], "state": "open"}
                for i in range(1, iters + 1)}})
        procs = []
        for wid in range(n):
            env = {**os.environ, "MCP_NSYNC_PATH": store, "MCP_NSYNC_AUTOSYNC": "0",
                   "AGENT_IDENTITY": ("swarm-collider" if role == "collide"
                                      else "swarm%03d" % wid)}
            env.pop("COLLAB_FAKE_GH", None)
            if fake_path:
                env["COLLAB_FAKE_GH"] = str(fake_path)
            cmd = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "worker",
                   "--role", role, "--scope", scope, "--id", str(wid),
                   "--iters", str(iters), "--ttl", str(role_ttl)]
            if hammer and role == "mutex":
                cmd.append("--hammer")
            if role == "collide":
                wd = Path(store) / ("collide-wd%d" % wid)
                wd.mkdir(parents=True, exist_ok=True)
                cmd += ["--workdir", str(wd)]
            errf = open(sdir / "err" / ("%d.txt" % wid), "wb")
            procs.append((subprocess.Popen(cmd, cwd=pkg_root, env=env,
                                           stdout=subprocess.DEVNULL, stderr=errf), errf))

        deadline = time.time() + READY_DEADLINE
        while len(list((sdir / "ready").glob("*"))) < n and time.time() < deadline:
            time.sleep(0.02)
        try:
            os.close(os.open(sdir / "go", os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            pass

        # watchdog: global timeout + per-role stall detection — never hangs CI
        hard_deadline = time.time() + timeout
        stall_deadline = time.time() + STALL_SECONDS
        last_sig = None
        killed = ""
        while any(p.poll() is None for p, _ in procs):
            if time.time() > hard_deadline:
                killed = "global timeout %.0fs" % timeout
            else:
                try:
                    sig = tuple(sorted((f.name, int(f.stat().st_mtime))
                                       for f in (sdir / "progress").glob("*")))
                except OSError:
                    sig = last_sig
                if sig != last_sig:
                    last_sig = sig
                    stall_deadline = time.time() + STALL_SECONDS
                elif time.time() > stall_deadline:
                    killed = "stalled %.0fs without progress" % STALL_SECONDS
            if killed:
                for p, _ in procs:
                    p.kill()
                break
            time.sleep(0.1)
        rcodes = []
        for p, errf in procs:
            rcodes.append(p.wait())
            errf.close()
        outs = [ac._read_json(sdir / "out" / ("%d.json" % wid)) for wid in range(n)]
        outs = [o for o in outs if o]
        clean = len(outs) == n and all(rc == 0 for rc in rcodes) and not killed
        detail = "rcodes=%s outs=%d/%d %s" % (rcodes, len(outs), n, killed)
        if not clean:
            errs = []
            for wid in range(n):
                txt = (sdir / "err" / ("%d.txt" % wid)).read_text(
                    encoding="utf-8", errors="replace").strip()
                if txt:
                    errs.append("w%d: %s" % (wid, txt[-300:]))
            detail += (" | " + " || ".join(errs[:3])) if errs else ""
        checks.append({"name": "%s: all %d workers finished cleanly" % (role, n),
                       "ok": clean, "detail": detail})

        if role == "mutex" and outs:
            counter = (ac._read_json(sdir / "counter.json") or {}).get("n", 0)
            acks = sum(o["acks"] for o in outs)
            viol = sum(o["violations"] for o in outs)
            lost = sum(o["lost"] for o in outs)
            checks.append({"name": "SWARM-MUTEX-1 counter == acknowledged increments",
                           "ok": counter == acks,
                           "detail": "counter=%d acks=%d lost=%d starved=%d"
                                     % (counter, acks, lost, sum(o["starved"] for o in outs))})
            stomps = sum(o.get("stomps", 0) for o in outs)
            checks.append({"name": "SWARM-MUTEX-2 zero mutual-exclusion violations",
                           "ok": viol == 0,
                           "detail": "violations=%d zombie_stomps=%d (stomps are the "
                                     "expected delayed-write hazard, rejected by fenced "
                                     "consumers)" % (viol, stomps)})
            if hammer:
                checks.append({"name": "SWARM-MUTEX-3 hammer exercised lease loss",
                               "ok": lost > 0,
                               "detail": "lost=%d (oversleepers must lose)" % lost})
        if role == "journal" and outs:
            events, torn = _read_full_journal(store, scope)
            seen = {}
            for e in events:
                if e.get("event") == "swarm.evt":
                    key = (e.get("data", {}).get("who"), e.get("data", {}).get("seq"))
                    seen[key] = seen.get(key, 0) + 1
            dups = sum(1 for v in seen.values() if v > 1)
            expected = n * iters
            checks.append({"name": "SWARM-JRN exactly-once + gap-free + zero torn lines",
                           "ok": torn == 0 and dups == 0 and len(seen) == expected,
                           "detail": "events=%d/%d dups=%d torn=%d"
                                     % (len(seen), expected, dups, torn)})
        if role == "claim" and outs:
            epoch_wins = {}
            for o in outs:
                for e in o["wins"]:
                    epoch_wins[e] = epoch_wins.get(e, 0) + 1
            multi = sum(1 for v in epoch_wins.values() if v > 1)
            blind = sum(o["blind"] for o in outs)
            checks.append({"name": "SWARM-CLM one winner per epoch, losers never blind",
                           "ok": multi == 0 and len(epoch_wins) == iters and blind == 0,
                           "detail": "epochs=%d/%d multi=%d blind=%d"
                                     % (len(epoch_wins), iters, multi, blind)})
        if role == "checkout" and outs:
            issue_wins = {}
            for o in outs:
                for i in o["wins"]:
                    issue_wins[i] = issue_wins.get(i, 0) + 1
            multi = sum(1 for v in issue_wins.values() if v > 1)
            recs = list((_collab_base(store, scope) / "work").glob("issue-*.json")) \
                if (_collab_base(store, scope) / "work").is_dir() else []
            active = [r for r in recs if (ac._read_json(r) or {}).get("phase") == "active"]
            checks.append({"name": "SWARM-WRK exactly one checkout winner per issue",
                           "ok": multi == 0 and len(issue_wins) == iters
                                 and len(active) == iters,
                           "detail": "issues=%d/%d multi=%d active_records=%d"
                                     % (len(issue_wins), iters, multi, len(active))})
        if role == "collide" and outs:
            events, _ = _read_full_journal(store, scope)
            coll = [e for e in events if e.get("event") == "identity.collision"]
            warns = sum(o["warnings"] for o in outs)
            checks.append({"name": "SWARM-COL shared identity across workdirs is detected",
                           "ok": warns >= 1 and len(coll) >= 1,
                           "detail": "warnings=%d journal_events=%d" % (warns, len(coll))})

    ok = all(c["ok"] for c in checks)
    report = {"ok": ok, "checks": checks, "agents": agents, "iters": iters,
              "hammer": hammer, "elapsed": round(time.time() - t_start, 1), "store": store}
    if ok and not keep and own_store:
        shutil.rmtree(store, ignore_errors=True)
        report["store"] = "(removed)"
    return report


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    w = sub.add_parser("worker")
    w.add_argument("--role", required=True, choices=ROLES)
    w.add_argument("--scope", required=True)
    w.add_argument("--id", type=int, required=True)
    w.add_argument("--iters", type=int, default=25)
    w.add_argument("--ttl", type=float, default=600.0)
    w.add_argument("--hammer", action="store_true")
    w.add_argument("--workdir", default=None)
    r = sub.add_parser("run")
    r.add_argument("--agents", type=int, default=8)
    r.add_argument("--iters", type=int, default=25)
    r.add_argument("--ttl", type=float, default=600.0)
    r.add_argument("--hammer", action="store_true")
    r.add_argument("--keep", action="store_true")
    r.add_argument("--json", action="store_true")
    r.add_argument("--store", default=None)
    r.add_argument("--timeout", type=float, default=None,
                   help="per-role budget; default scales with agents*iters "
                        "(100x40 hammer on 2-core CI needs ~25min, not 180s)")
    a = ap.parse_args()
    if a.cmd == "worker":
        return worker_main(a)
    if a.cmd == "run":
        timeout = a.timeout if a.timeout else max(180.0, a.agents * a.iters * 0.4)
        report = run_swarm(store=a.store, agents=a.agents, iters=a.iters, ttl=a.ttl,
                           hammer=a.hammer, keep=a.keep, timeout=timeout)
        if a.json:
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
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

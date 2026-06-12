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
  work list                           (open GitHub issues + who has them checked out)
  work start <issue#> [--branch]      (check OUT an issue: assign + label, claim, journal)
  work done <issue#> [--pr URL]       (close it — or link the PR — and release everything)
  work drop <issue#>                  (un-checkout without finishing)
  work tick <issue#> <item#>          (tick task-list checkbox N inside the issue body)
  journal log <event> [--data JSON]
  journal tail [N]
  status                              (presence + leases + claims + work + journal, one view)
  heartbeat [STATUS] [TASK]           (presence beat — also detects identity collisions)
  onboard                             (print the complete join-the-team procedure for an agent)
  selftest                            (verify the whole engine on an isolated scope)
  whoami

WORK = GitHub-native collaboration: an agent's unit of work is a GitHub issue, checked out
like a lease. `work start` assigns the issue, labels it `in-progress` + `agent:<callsign>`,
creates the matching claim (issue URL in its note), records it in the store, and journals
`work.start`. All GitHub access goes through the `gh` CLI and degrades with a clear error
when gh/network is absent — leases/claims/journal never depend on it.

IDENTITY RULE: one working directory = one agent identity. If two sessions in DIFFERENT
directories heartbeat the same identity, status/heartbeat warn loudly (identity collision —
leases cannot protect sessions that look like one agent). Give each session its own checkout
(e.g. `git worktree add`) and its own call-sign.
"""

from pathlib import Path
import json
import os
import re
import shutil
import subprocess
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
    if not claim_id or not pattern:
        return False, {"owner": "nobody — a claim needs a non-empty id and pattern"}
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


# ── work (GitHub issues checked out like leases — gh-backed) ──────────────────────────────────
GH_TIMEOUT = 30
WORK_STALE_HOURS = 24.0   # someone else's checkout may be dropped after this long


def _gh_real(gh_args):
    """Run the gh CLI. Returns (ok, stdout_or_error). This is the ONLY GitHub
    touchpoint of the work verbs — selftest swaps GH_RUNNER for an offline fake."""
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


GH_RUNNER = _gh_real


def _gh_json(gh_args):
    ok, out = GH_RUNNER(gh_args)
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


def work_start(project: str, issue, who: str, make_branch: bool = False):
    """Check OUT a GitHub issue like a lease: assign + label it, create the matching
    claim (issue URL in its note), record + journal it. Returns (ok, message)."""
    issue = int(issue)
    rec = _read_json(work_path(project, issue))
    if rec and rec.get("owner") != who:
        age_h = (_now() - rec.get("started", 0)) / 3600.0
        if age_h < WORK_STALE_HOURS:
            return False, ("issue #%d is checked out by %s (%.1fh ago) — coordinate via "
                           "collab message/journal, or `work drop %d` once it is stale"
                           % (issue, rec.get("owner"), age_h, issue))
    ok, meta = _gh_json(["issue", "view", str(issue),
                         "--json", "number,title,url,body,labels,assignees"])
    if not ok:
        return False, meta
    title, url = meta.get("title", ""), meta.get("url", "")
    paths = extract_paths(meta.get("body", ""))[:8]
    pattern = ",".join(paths) if paths else url
    c_ok, c_info = claim_add(project, "issue-%d" % issue, pattern, who,
                             note="%s — %s" % (title, url))
    if not c_ok:
        return False, ("claim issue-%d is held by %s — that agent owns this issue's area"
                       % (issue, (c_info or {}).get("owner")))
    labels = "in-progress,agent:" + who
    lab_ok, lab_err = GH_RUNNER(["issue", "edit", str(issue), "--add-label", labels])
    if not lab_ok:                       # labels may not exist in the repo yet — create, retry
        GH_RUNNER(["label", "create", "in-progress", "--color", "FBCA04", "--force"])
        GH_RUNNER(["label", "create", "agent:" + who, "--color", "1D76DB", "--force"])
        lab_ok, lab_err = GH_RUNNER(["issue", "edit", str(issue), "--add-label", labels])
    GH_RUNNER(["issue", "edit", str(issue), "--add-assignee", "@me"])   # best-effort
    branch, branch_err = "", ""
    if make_branch:
        branch = "agent/%s/issue-%d" % (who, issue)
        try:
            subprocess.run(["git", "checkout", "-b", branch], capture_output=True,
                           text=True, timeout=30, check=True)
        except Exception as e:
            branch, branch_err = "", str(e)
    payload = {"issue": issue, "title": title, "url": url, "owner": who, "paths": paths,
               "branch": branch, "started": _now(), "started_ts": time.ctime()}
    work_path(project, issue).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    journal_log(project, who, "work.start",
                {"issue": issue, "title": title, "url": url, "paths": paths})
    msg = ("checked out issue #%d: %s\n  url: %s\n  claim: issue-%d -> %s"
           % (issue, title, url, issue, pattern))
    if not lab_ok:
        msg += "\n  [warn] labels not applied: %s" % lab_err
    if branch:
        msg += "\n  branch: %s" % branch
    elif branch_err:
        msg += "\n  [warn] branch not created: %s" % branch_err
    for ia, oa, ib, ob, ov in work_conflicts(project):
        if issue in (ia, ib):
            msg += ("\n  [CONFLICT RADAR] #%d (%s) and #%d (%s) both touch: %s"
                    % (ia, oa, ib, ob, ", ".join(ov[:5])))
    return True, msg


def work_done(project: str, issue, who: str, pr: str = ""):
    """Finish a checkout: close the issue (or link the PR and leave it open for
    review), drop the claim + record, journal work.done. Returns (ok, message)."""
    issue = int(issue)
    rec = _read_json(work_path(project, issue))
    if rec and rec.get("owner") != who:
        return False, ("issue #%d is checked out by %s — only its owner finishes it"
                       % (issue, rec.get("owner")))
    if pr:
        ok, err = GH_RUNNER(["issue", "comment", str(issue), "--body",
                             "Agent `%s` finished this work: %s" % (who, pr)])
        if ok:
            GH_RUNNER(["issue", "edit", str(issue), "--remove-label", "in-progress"])
    else:
        ok, err = GH_RUNNER(["issue", "close", str(issue), "--comment",
                             "Completed by agent `%s` (mcp collab work done)." % who])
    if not ok:
        return False, err
    GH_RUNNER(["issue", "edit", str(issue), "--remove-label", "agent:" + who])  # best-effort
    claim_drop(project, "issue-%d" % issue, who)
    work_path(project, issue).unlink(missing_ok=True)
    journal_log(project, who, "work.done", {"issue": issue, "pr": pr})
    return True, ("issue #%d done — linked %s (left open for review)" % (issue, pr)
                  if pr else "issue #%d closed" % issue)


def work_drop(project: str, issue, who: str):
    """Un-checkout without finishing: unlabel, drop the claim + record, journal."""
    issue = int(issue)
    rec = _read_json(work_path(project, issue))
    if rec and rec.get("owner") != who:
        age_h = (_now() - rec.get("started", 0)) / 3600.0
        if age_h < WORK_STALE_HOURS:
            return False, ("issue #%d is checked out by %s (%.1fh ago) — not stale yet"
                           % (issue, rec.get("owner"), age_h))
    owner = (rec or {}).get("owner", who)
    GH_RUNNER(["issue", "edit", str(issue),
               "--remove-label", "in-progress,agent:" + owner])           # best-effort
    claim_drop(project, "issue-%d" % issue, who)
    work_path(project, issue).unlink(missing_ok=True)
    journal_log(project, who, "work.drop", {"issue": issue, "owner": owner})
    return True, "issue #%d released" % issue


def work_list(project: str, who: str):
    """Open issues + who has them checked out locally. Returns (ok, text)."""
    ok, issues = _gh_json(["issue", "list", "--state", "open", "--limit", "50",
                           "--json", "number,title,labels,assignees,url"])
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


def work_tick(project: str, issue, item, who: str):
    """Tick the item-th task-list checkbox (1-based) inside the issue body."""
    issue, item = int(issue), int(item)
    ok, meta = _gh_json(["issue", "view", str(issue), "--json", "body,title"])
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
    ok, err = GH_RUNNER(["issue", "edit", str(issue), "--body", new_body])
    if not ok:
        return False, err
    journal_log(project, who, "work.tick", {"issue": issue, "item": item, "text": line[:120]})
    return True, "ticked #%d item %d: %s" % (issue, item, line[:80])


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
5. UNITS OF WORK are GitHub issues when the project has a remote: `mcp collab work list`
   to see what's open and who holds what, `work start <issue#>` to check one out (it
   assigns + labels the issue and creates your claim), `work done <issue#> [--pr URL]`
   when finished, `work drop <issue#>` to hand it back. Never start an issue another
   agent has checked out — status shows checkouts and the conflict radar.
6. JOURNAL everything material: intents before, results after —
   `mcp collab journal log intent --data '{"text": "..."}'`. Tail it at EVERY loop start.
7. LANDING WORK: acquire the git-commit lease -> fetch + rebase -> push -> release -> journal
   the commit hash.
8. Message any teammate: `mcp comms send <callsign> note "<text>"`; read yours each loop.
Projects may carry their own onboarding (e.g. a repo skill) with project-specific lease names —
that version wins on specifics.
"""


def _selftest_fake_gh(state):
    """Offline gh: a dict of issues behind the same (ok, out) contract as _gh_real."""
    def fake(gh_args):
        if state.get("offline"):
            return False, "gh CLI not found — offline fake"
        head = gh_args[:2]
        if head == ["issue", "view"]:
            n = int(gh_args[2])
            if n not in state["issues"]:
                return False, "issue #%d not found" % n
            iss = state["issues"][n]
            return True, json.dumps({"number": n, "title": iss["title"], "url": iss["url"],
                                     "body": iss["body"], "labels": [], "assignees": []})
        if head == ["issue", "edit"]:
            iss = state["issues"][int(gh_args[2])]
            if "--add-label" in gh_args:
                new = gh_args[gh_args.index("--add-label") + 1].split(",")
                iss["labels"] = sorted(set(iss["labels"]) | set(new))
            if "--remove-label" in gh_args:
                gone = set(gh_args[gh_args.index("--remove-label") + 1].split(","))
                iss["labels"] = [x for x in iss["labels"] if x not in gone]
            if "--body" in gh_args:
                iss["body"] = gh_args[gh_args.index("--body") + 1]
            return True, ""
        if head == ["issue", "close"]:
            state["issues"][int(gh_args[2])]["state"] = "closed"
            return True, ""
        if head == ["issue", "comment"]:
            state["issues"][int(gh_args[2])].setdefault("comments", []).append(
                gh_args[gh_args.index("--body") + 1])
            return True, ""
        if head == ["issue", "list"]:
            return True, json.dumps(
                [{"number": k, "title": v["title"], "url": v["url"], "assignees": [],
                  "labels": [{"name": x} for x in v["labels"]]}
                 for k, v in state["issues"].items() if v["state"] == "open"])
        if gh_args[:1] == ["label"]:
            return True, ""
        return False, "fake gh: unhandled %s" % " ".join(gh_args[:3])
    return fake


def selftest():
    """Verify the engine end-to-end on an isolated scope. Returns (ok, lines)."""
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

    global GH_RUNNER
    saved_runner = GH_RUNNER
    state = {"issues": {
        7: {"title": "Wire the flux capacitor", "url": "https://github.com/x/y/issues/7",
            "body": "Touch src/flux.py and docs/flux.md\n- [ ] wire it\n- [ ] test it",
            "labels": [], "state": "open"},
        9: {"title": "Polish the flux capacitor", "url": "https://github.com/x/y/issues/9",
            "body": "Also edits src/flux.py", "labels": [], "state": "open"},
    }}
    try:
        GH_RUNNER = _selftest_fake_gh(state)
        s_ok, _ = work_start(P, 7, "selfA")
        claims = {c["id"]: c for c in claims_all(P)}
        rec = _read_json(work_path(P, 7))
        tail_evs = [e["event"] for e in journal_tail(P, 10)]
        check("work start = labels + claim(url in note) + record + journal",
              s_ok and "in-progress" in state["issues"][7]["labels"]
              and "agent:selfA" in state["issues"][7]["labels"]
              and "issue-7" in claims and "issues/7" in claims["issue-7"]["note"]
              and "src/flux.py" in claims["issue-7"]["pattern"]
              and rec is not None and rec.get("owner") == "selfA"
              and "work.start" in tail_evs)
        b_ok, b_msg = work_start(P, 7, "selfB")
        check("work checkout exclusivity", not b_ok and "selfA" in b_msg)
        r_ok, r_msg = work_start(P, 9, "selfB")
        radar = work_conflicts(P)
        check("conflict radar flags overlapping checkouts",
              r_ok and "CONFLICT RADAR" in r_msg
              and any({pair[0], pair[2]} == {7, 9} for pair in radar))
        t_ok, _ = work_tick(P, 7, 1, "selfA")
        check("work tick flips the checkbox",
              t_ok and "- [x] wire it" in state["issues"][7]["body"]
              and "- [ ] test it" in state["issues"][7]["body"])
        d_ok, _ = work_done(P, 7, "selfA")
        check("work done closes + releases claim + record",
              d_ok and state["issues"][7]["state"] == "closed"
              and "issue-7" not in {c["id"] for c in claims_all(P)}
              and not work_path(P, 7).exists())
        work_drop(P, 9, "selfB")
        state["offline"] = True
        o_ok, o_msg = work_start(P, 7, "selfA")
        check("work degrades clearly without gh",
              not o_ok and "gh" in o_msg.lower() and not work_path(P, 7).exists()
              and "issue-7" not in {c["id"] for c in claims_all(P)})
    finally:
        GH_RUNNER = saved_runner
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
        print("\n-- work (gh issues checked out) --")
        ws = work_all(project)
        if not ws:
            print("  (none)")
        for w in ws:
            b = f" branch={w['branch']}" if w.get("branch") else ""
            print(f"  #{w['issue']:<5} {w.get('title', '')[:48]}  (owner {w['owner']}{b})")
        for ia, oa, ib, ob, ov in work_conflicts(project):
            print(f"  [CONFLICT RADAR] #{ia} ({oa}) and #{ib} ({ob}) both touch: {', '.join(ov[:5])}")
        print("\n-- journal (last 10) --")
        for e in journal_tail(project, 10):
            print(f"  {e['ts']}  {e['who']:<16} {e['event']:<20} {json.dumps(e['data'], ensure_ascii=False)[:100]}")
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())

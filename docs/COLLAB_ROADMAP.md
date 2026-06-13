# Multi-Agent Collab: FIRST-CLASS — the active roadmap (2026-06-11)

**The user's standing directive for this project:** make multi-agent collaboration first-class
and as powerful as possible — including deep GitHub integration (issues, tasks, projects) and
automated workflows that auto-detect the impact of any issue/task an agent checks out.
**Extended 2026-06-11:** support 100 CONCURRENT AGENTS per project (including many on one
device), atomic primitives throughout, and E2E testing expected for every commit.

## 100-AGENT SOAK — PROVEN GREEN BOTH OSes 2026-06-13 (Quasar)
The headline claim is now empirically settled. CI run 27456474140 (commit 7a8c805), 100
concurrent agents, hammer-mode lease churn, on ubuntu AND windows: MUTEX-1 final counter ==
committed increments (3584/3546, zero lost updates), MUTEX-2 zero double-holding, MUTEX-3
416/454 forced lease losses, JRN 4000/4000 events exactly-once + zero torn, CLM 40/40
one-winner-per-epoch, WRK 40/40 one-checkout-per-issue, COL collision detected. Getting
there hardened the *harness*, not the engine: the original MUTEX-1 reconstructed a linear
chain over the fenced register, but under true concurrency fence-order != write-order, so
inert orphan writes formed cycles in the reconstruction (and OOM'd on the unbounded walk).
Replaced by the direct invariant — only a STILL-VALID holder commits the shared counter
(lease_valid before the RMW; a fresh-TTL lease keeps the 3ms section inside the 0.5s hold),
so `final == acks` is race-free and O(1). The engine's mutual exclusion (MUTEX-2) and the
fenced register were correct throughout.

## CROSS-MACHINE SYNC-SAFETY — PROVEN 2026-06-13 (issue #20, Quasar)
The stated "not just different devices" goal is now VERIFIED, not just asserted. A test
builds two independent stores, runs lease/journal/claim churn in each, merges their files
both ways (union, as NSync/git propagation does), and proves the merged state is consistent:
fence high-water = max via O_EXCL **marker union** (the next acquire mints a fence above
BOTH machines — monotonicity preserved cross-machine), every journal event from both present
and time-ordered, claims union, zero corruption. Satisfying confirmation that the fence.d
marker design (introduced reactively during the soak) is precisely what makes fencing
sync-safe — markers union by value where a single sidecar file would conflict. HONEST LIMITS
(by design, documented): a *lease* on the same resource can be held on two machines until
sync propagates (advisory cross-machine, resolved by fencing — the lower/owner-mismatched
holder fails its next `lease_valid`); STRONG cross-machine exclusion for WORK is the GitHub
`state:available` label CAS, not the file store. No gap surfaced; the test is a permanent guard.

## OPERABILITY: fleet metrics from the journal — SHIPPED 2026-06-13 (issue #16, Quasar)
`agent_collab.collab_metrics(project, hours)` turns the append-only journal into a fleet
analytics source: throughput (work started/completed/in-flight/dropped/lost-race), CYCLE
TIME (work.start→completion paired by issue: count + mean/p50/p90 minutes), lease churn,
contention (collisions/merge-races/lost-races), and top agents — over a window, pure read,
bounded + corruption-tolerant. CLI `mcp collab metrics [--hours N] [--json]`; a compact 24h
line now rides `collab status` / `join` and the `collab_status` MCP tool. The third
observability lens after the dashboard (current state) and `doctor` (health): how is the
fleet PERFORMING. Live on this repo it already surfaced the real PR-#4 merge-race and the
clean 22/22 lease acquire/release churn. Test pins throughput, cycle math, and windowing.

## OPERABILITY: collab health in `mcp doctor` — SHIPPED 2026-06-13 (issue #12, Quasar)
`mcp doctor` / `mcp verify` gained a Collab Store dimension: the reusable
`agent_collab.collab_health(project)` (pure diagnosis — agents live/total, identity
collisions, orphaned claims, abandoned checkouts, stale leases, corrupt files, stray
artifacts, journal size, checkout conflicts) feeds the Doctor's text + `--json health_score`,
and `mcp doctor --fix` self-heals via `collab_heal` (the janitor, now also reaping genuinely-
corrupt records) — never touching live state. This consolidates the hand-cleanup a 100-agent
fleet operator otherwise does (exactly what was done by hand during the freeze incident) into
one command. selftest + a pytest pin detection and heal.

## HARNESS RESOURCE SAFETY — SHIPPED 2026-06-12/13 (Quasar)
A verification harness must NEVER be able to take down the machine it runs on. The swarm
spawned `agents` worker PROCESSES all at once; overlapping runs (the pre-push hook's swarm +
a manual run + pytest's swarm tests) compounded into a process storm that nearly froze a
20-core/16 GB dev box, and a second run drove RAM to 0 GB. Two structural fixes:
(1) `run_swarm` runs a BOUNDED POOL — all `agents` identities still run, but at most
`max_parallel` have a live OS process at once (default `_safe_parallel` = CPU/2, floor 2;
CI soak passes 16). The bound ALONE makes overlapping runs safe (a few × CPU/2 stays within
core count), so no fragile global lock is needed. (2) The pre-push hook runs the heavy ML
suite and the subprocess-spawning swarm tests in SEPARATE pytest processes, so swarm
subprocesses never stack on the parent's torch/model imports (RAM 0 GB -> 5.6 GB min). Guard
tests pin the cap; the MUTEX-1 chain walk is cycle-safe + bounded so a verification check can
never infinite-loop. Because the invariants are correctness invariants, bounded sustained
contention proves them as rigorously as an all-at-once burst.

## THE SCALE TIER — SHIPPED 2026-06-11 (Quasar)
Selftest 41/41 green (incl. adversarial-review hardening: CAS renew that can never
resurrect an expired lease, CAS claim refresh, fence high-water preserved across
retirement, seat reclaim through the O_EXCL gate, idle-but-seated callsigns never
reused); swarm invariants proven at 16 processes per commit (CI), 100 nightly.

- **Atomic store discipline** — every write is O_EXCL create / temp+`os.replace`
  (`atomic_write_json`) / rename-to-unique-tombstone (`_cas_take`); a write-discipline test
  greps the source so truncating writes can never regress. `_read_json` retries transient
  Windows sharing violations: None ⇔ absent-or-corrupt, never mid-write.
- **Fenced leases** — monotonic fence per acquisition (sidecar high-water mark survives
  releases), incarnation-checked renew, `lease valid --fence N` before irreversible acts,
  corrupt-lease recovery (no permanent deadlock), break via take-verify-restore (a live
  owner's lease is never silently destroyed), full-jitter waits (no thundering herd).
- **Seats: same-device multi-agent** — `.mcp/seat.json` binds workdir→call-sign (create-once
  O_EXCL); `identity()` resolves env > seat > hostname; `collab seat new <cs>` provisions a
  git-worktree seat in one command; `collab join` = seat + heartbeat + engine probe + status.
  Cross-workdir use of one identity is REFUSED at the lease/claim/work layer.
- **Transactional checkouts** — work records go pending→active with rollback on gh failure;
  a 5-line label guard refuses GitHub-side foreign checkouts (cross-machine window).
- **Sharded journal** — per-writer segments (`journal/<id>.<pid>.ndjson`, single O_APPEND
  syscall per event), merged bounded tails, unique-rename rotation, torn lines skipped.
- **Maildir mailboxes** — per-recipient dirs, claim-by-rename consumption (unique claim
  names: deterministic rename destinations are NOT a CAS on Windows — empirically two
  concurrent renames to one destination can both report success), legacy layout read forever.
- **Janitor GC** — `collab gc` + opportunistic election via the `janitor` lease from
  `status`; bounded reaping of stale presence/claims/orphans/strays; per-store invariant.
- **Swarm harness** — `collab swarmtest`: N real OS processes (spawn-safe, watchdogged)
  prove SWARM-MUTEX (no lost increments, no double-occupancy, fencing under forced expiry),
  SWARM-JRN (exactly-once, gap-free, zero torn), SWARM-CLM/WRK (single winner), SWARM-COL
  (collision detection). pytest markers `swarm`/`soak`; 100-agent soak nightly.
- **E2E per commit** — pre-commit hook: collab E2E gate (no tree mutation); pre-push hook:
  selftest + full suite + 6-process swarm + security; CI (`ci.yml`): selftest + suite +
  16-process swarm on ubuntu AND windows (required contexts pinned by
  `REQUIRED_CHECK_CONTEXTS`); `collab-soak.yml`: nightly 100-agent hammer with
  auto-filed `swarm-regression` issues.

**Cross-machine claim arbitration — SHIPPED 2026-06-12:** `work start` atomically removes
the `state:available` label (GitHub's one-winner primitive — the second DELETE gets 404):
exactly one machine wins a checkout even though every agent shares one GitHub login. Lost
races leak nothing locally; repos without seeded labels degrade to advisory-local with a
post-label verification (deterministic lexicographic tie-break, exactly one side
self-drops). `work verify <issue#>` re-confirms a checkout at loop start / before pushing
and SELF-DROPS lost checkouts (journal `work.lost_race`) so two machines never finish the
same issue; `work drop` returns the label. Selftest 45/45.

**PR landing path — SHIPPED 2026-06-12:** `work submit <n>` pushes the issue branch, opens
(or crash-safely ADOPTS) the PR — body leads with `Closes #N` so the merge closes the
issue — arms auto-merge behind the required CI checks, labels `state:review`, journals
`work.submit`. `work land <n>` is the single-shot landing pass: finalizes a MERGED PR
(claim + record released, remote branch deleted, `work.landed`), heals a BEHIND/unarmed
one, reports conflicts. `work done` redirects to `land` when a submitted PR is open.
At scale, agents never push master directly. Selftest 48/48.

**Repo provisioning — SHIPPED + APPLIED LIVE 2026-06-12:** `collab github-setup [--apply]`
(dry-run default) creates the coordination labels, seeds `state:available` onto unlabeled
open issues, and installs the `master-gate` ruleset: PR required, the two CI contexts
pinned by `REQUIRED_CHECK_CONTEXTS` required + strict up-to-date, force-push/deletion
blocked, admin break-glass bypass (the shared owner token stays unblocked). `--apply`
REFUSES if the contexts don't match real check runs on the default branch — a typo can
never hard-block all merging. Applied to THIS repo: ruleset id 17613013 active.
Selftest 51/51.

**Issue forms — SHIPPED 2026-06-12:** `.github/ISSUE_TEMPLATE/agent-task.yml` (Objective /
Files-areas-touched / Blocked by / Acceptance checks / Priority / Area; auto-labels
`state:available`) + the shared `parse_issue_form()` — section labels are a pinned contract
(`FORM_FIELDS`, enforced by a CI test against the template). Form-declared paths drive the
claim, the conflict radar, and the auto-impact report (free text still falls back to
extraction); OPEN `Blocked by` dependencies REFUSE `work start` (checked before the label
CAS so a refusal never consumes `state:available`; `--force` overrides). Selftest 54/54.

**Shared gh transport — SHIPPED 2026-06-12 (issue #1, landed via the system's own PR
path):** `issues_cached()` serves the team's issue list from a 45s-TTL shared cache (one
refresher elected via the `gh-issues-fetch` lease; everyone else gets stale-while-
revalidate) — N agents polling for work cost ~one gh call per TTL, not N. `_gh_gated()`
puts every transport call behind a SHARED penalty gate: any 403/429 trips a jittered
back-off window for the whole team (no stampede on a shared token); corrupt/missing gate
files fail OPEN. `work list` rides the cache. Selftest 57/57.

**Fleet self-organization — SHIPPED 2026-06-12 (issue #3):** `collab work next [--start]`
picks the best NON-CONFLICTING ready issue with no human dispatcher: candidates from the
shared cache, minus checked-out/labeled/blocked issues; the busy set is every active
checkout's impact closure (prebuilt `.mcp/impact_graph.json`, suffix-matched, never rebuilt
inline); ranked by (no-overlap, priority, MOST-UNBLOCKING, blast radius, number) with
per-agent sha1 rotation inside the equal (overlap, priority, unblocks) tier so identical
fleets fan out instead of stampeding one issue. `--start` checks the pick out and NEVER
auto-picks overlapping work. **CRITICAL-PATH added 2026-06-13 (issue #18):** within a
priority tier, an issue that unblocks more downstream `Blocked by` work is drained first
(`[unblocks=N]` shown), so the fleet naturally clears bottlenecks instead of stranding
blocked work. Plus a
landing-race guard born from production: auto-merge fired on an old head concurrently with
a fresh push on PR #4 and silently dropped a commit — `work land` now refuses to finalize
while local commits are missing from the merged tree (journals `work.merge_race`).
Selftest 60/60.

**Reconciler — SHIPPED 2026-06-12 (issue #2, picked by `work next` itself):**
`agent-reconcile.yml` (cron */10, dispatch, repository_dispatch[agent-sync]; singleton;
GITHUB_TOKEN only) runs `swarm_reconcile.py`: ONE batched GraphQL read, a pure
level-triggered `plan()` (re-seed `state:available` on label-less open issues, dedupe
agent-impact comment families keeping the lowest id, maintain the pinned Swarm Dashboard),
individually idempotent mutations, ndjson audit log. Tests prove convergence to zero actions.
**RECLAIM added 2026-06-13 (issue #14):** an in-progress issue with no GitHub activity for
>RECLAIM_HOURS (24h) is abandoned — strip `in-progress` + `agent:*`, return it to
`state:available`, post an audit comment. Closes the GitHub-side durability gap (a crashed
agent's checkout otherwise stays in-progress forever); composes with `work verify`, which
self-drops a wrongly-reclaimed live agent's local checkout. Driven by `updatedAt` (refreshed
by `work tick` and the reclaim comment itself), idempotent (no in-progress -> no re-reclaim).

**THE SCALE BLUEPRINT IS COMPLETE (items 1-20, plus the self-update system).** The full
loop stands: form-issues -> atomic checkout (label CAS) -> fleet self-assignment
(`work next`) -> gated PR landing (auto-merge behind required checks, merge-race guard) ->
reconciler cleanup -> self-updating installs delivering each release to every user at
session start. Releases: v2.2.0 (scale tier), v2.3.0 (update era), v2.4.0 (blueprint
complete). Future innovation continues through the lifecycle itself: file an agent-task
issue, let `work next` route it.

## Where it stands (v2.1.0, commit 9c0f035)
Built and verified (`mcp collab selftest` = 6/6 green):
- **Leases** — exclusive TTL'd locks (atomic O_EXCL, re-entrant, stale auto-break, `--wait`).
- **Claims** — advisory source-area ownership.
- **Journal** — append-only per-project radio channel (auto-rotated at 2 MB).
- **Presence** — workdir-aware heartbeats + IDENTITY-COLLISION detection (one workdir = one
  agent; violations warn loudly and journal `identity.collision`).
- **Onboarding** — `mcp collab onboard` prints the generic join-the-team procedure; the phrase
  "you are an additional agent" resolves to an exact procedure.
- **MCP tools** — collab_status / collab_lease / collab_journal / collab_message / collab_claim.
- **The store contract** — plain files at `~/.mcp/nsync/.nsync_agents/collab/<project>/`;
  zero-dep clients may speak it directly. First consumer: AI_Gen (UE 5.7) — its bridge layer
  REFUSES editor commands without the `editor` lease (structural enforcement, the model to copy).
- Battle log: a real two-session shakedown on AI_Gen surfaced the same-identity hazard (caused a
  six-fixture test cascade) → the collision detector. Read that history in the AI_Gen project's
  collab journal and `.claude/skills/collab-onboard/`.

## THE NEXT TIER — GitHub-native collaboration (highest priority)
Goal: an agent's unit of work becomes a **GitHub issue**, checked out like a lease, with
automation that tells the team what that work touches.

**STATUS 2026-06-11 (Quasar): items 1–5 SHIPPED — selftest 12/12 green.** The work verbs,
status sync, conflict radar, task-list ticking, and both GitHub Actions are in. All GitHub
access funnels through one swappable runner (`agent_collab.GH_RUNNER`) so the selftest
verifies the entire checkout lifecycle offline. Bonus, forced by dogfooding: the impact
engine now resolves Python RELATIVE imports (`from . import x`) and sys.path-rooted
subpackage imports — before that, issue-impact reports called everything a leaf file.
Remaining from this tier: co-modification correlations (`correlate`) in the Action comment,
and warning on BOTH issues when the radar fires (today the comment lands on the
triggering issue/PR only).

1. **`collab work` verbs (gh-backed work checkout)** — DONE. `work list` (open issues + local
   checkouts), `work start <issue#> [--branch]` (assign @me, label `in-progress` +
   `agent:<callsign>` — labels auto-created — create the matching claim + work record +
   journal entry, optional branch `agent/<callsign>/issue-<n>`), `work done <issue#>
   [--pr URL]` (close, or link the PR and leave open for review; releases claim + record),
   `work drop <issue#>` (un-checkout; others may drop after 24h staleness). Clear error
   when `gh`/network is absent; exposed as the `collab_work` MCP tool too.
2. **Auto-impact on checkout (GitHub Actions)** — DONE (first cut). `.github/workflows/
   agent-issue-impact.yml` fires on assignment / `in-progress` label, extracts paths from
   the issue body (`agent_collab.extract_paths`), runs `scripts/impact_report.py` (built on
   this package's `impact` engine), and UPSERTS one marker-keyed comment: direct importers,
   transitive dependents, affected tests, conflict radar vs other in-progress issues.
   `agent-pr-impact.yml` is the on-PR variant over the diff. Not yet: `correlate`
   co-modification data in the comment.
3. **Issue ⇄ collab sync** — DONE. `collab status` (CLI + MCP) shows a work section with each
   agent's checked-out issues; journal logs work.start/work.done/work.drop/work.tick with
   issue numbers; claims from `work start` carry the issue URL in their note.
4. **Conflict radar** — DONE in `collab status`/`work list`/`work start` (path-set
   intersection of checkouts) and in both Action comments (impact-set intersection vs other
   in-progress issues). Not yet: posting the warning on BOTH overlapping issues.
5. **Task lists** — DONE: `work tick <issue#> <n>` ticks the n-th checkbox in the issue body
   and journals it.

Principles (inherited from the AI_Gen battle-testing): structural enforcement over etiquette;
stale state must self-heal; every capability gets a selftest; file formats are contracts;
the repo carries the knowledge (per-session memory does not transfer).

## Working agreements for sessions on THIS repo
- Join the collab scope: `python mcp-agentic-rules/mcp.py collab join <callsign> --project mcp-agentic-context`
  (one workdir = one agent — the seat file enforces it; heartbeat + journal your intents).
- Serialize pushes to master with the `git-commit` lease on the `mcp-agentic-context` scope.
- `mcp collab selftest` AND `mcp collab swarmtest` must stay green; extend them with every
  new collab capability. The hooks + CI enforce both on every commit — never bypass them.
- The store file formats are contracts (fence sidecars, journal segments, seat files,
  maildir names documented above) — zero-dep clients read these files directly.

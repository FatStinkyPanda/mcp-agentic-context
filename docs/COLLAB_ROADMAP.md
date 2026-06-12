# Multi-Agent Collab: FIRST-CLASS — the active roadmap (2026-06-11)

**The user's standing directive for this project:** make multi-agent collaboration first-class
and as powerful as possible — including deep GitHub integration (issues, tasks, projects) and
automated workflows that auto-detect the impact of any issue/task an agent checks out.
**Extended 2026-06-11:** support 100 CONCURRENT AGENTS per project (including many on one
device), atomic primitives throughout, and E2E testing expected for every commit.

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

Remaining from the scale blueprint (follow-up order): issue forms + shared parser, shared
gh issue cache + rate-limit penalty gate, reconciler workflow (seed/dedupe), `work next`
conflict-aware auto-assignment.

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

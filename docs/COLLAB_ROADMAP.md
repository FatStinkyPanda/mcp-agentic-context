# Multi-Agent Collab: FIRST-CLASS — the active roadmap (2026-06-11)

**The user's standing directive for this project:** make multi-agent collaboration first-class
and as powerful as possible — including deep GitHub integration (issues, tasks, projects) and
automated workflows that auto-detect the impact of any issue/task an agent checks out.

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
- Join the collab scope: `python mcp-agentic-rules/mcp.py collab status --project mcp-agentic-context --as <callsign>`
  (one workdir = one agent; heartbeat + journal your intents).
- Serialize pushes to master with the `git-commit` lease on the `mcp-agentic-context` scope.
- `mcp collab selftest` must stay green; extend it with every new collab capability.

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

1. **`collab work` verbs (gh-backed work checkout)** — `mcp collab work list` (open issues with
   labels/assignees), `work start <issue#> --as <agent>` (assign to the agent's GitHub identity
   or label `agent:<callsign>`, add `in-progress`, create the matching claim + journal entry,
   optionally create branch `agent/<callsign>/issue-<n>`), `work done <issue#>` (PR link or
   close + drop claim + journal), `work drop <issue#>`. Build on the `gh` CLI (already authed
   as FatStinkyPanda); degrade gracefully (clear error) when `gh`/network is absent.
2. **Auto-impact on checkout (GitHub Actions)** — a workflow (`.github/workflows/`) that fires
   on issue assignment / `in-progress` label: parses file paths + symbols out of the issue body,
   runs this package's OWN `impact` + `graph`/`correlate` analyzers on them, and posts a comment:
   what imports the touched files (transitively), affected tests, co-modification correlations,
   and which OTHER open issues/claims overlap (conflict early-warning between agents). Also an
   on-PR variant commenting impact on the diff.
3. **Issue ⇄ collab sync** — `collab status` shows each agent's checked-out issues next to its
   leases/claims; the journal logs work.start/work.done with issue numbers; claims created by
   `work start` carry the issue URL in their note.
4. **Conflict radar** — when two open in-progress issues' impact sets intersect, warn on both
   issues (Action comment) and in `collab status`.
5. **Task lists** — support GitHub task-list checkboxes inside an issue as sub-task state agents
   can tick via `work tick <issue#> <n>`.

Principles (inherited from the AI_Gen battle-testing): structural enforcement over etiquette;
stale state must self-heal; every capability gets a selftest; file formats are contracts;
the repo carries the knowledge (per-session memory does not transfer).

## Working agreements for sessions on THIS repo
- Join the collab scope: `python mcp-agentic-rules/mcp.py collab status --project mcp-agentic-context --as <callsign>`
  (one workdir = one agent; heartbeat + journal your intents).
- Serialize pushes to master with the `git-commit` lease on the `mcp-agentic-context` scope.
- `mcp collab selftest` must stay green; extend it with every new collab capability.

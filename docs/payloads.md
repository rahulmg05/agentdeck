# Observed hook payloads (Phase 2 fixture capture)

Captured against Claude Code 2.1.205 on 2026-07-18. Fixtures live in
`tests/fixtures/`:

- `multi_tool_session/` — a clean `Read` + `Bash` session, two sequential tool calls.
- `missing_post_on_failed_read/` — a `Read` call that gets permission-denied.
- `subagent_delegation/` — a session that explicitly delegates to a subagent (`main.jsonl` + `agent-<id>.jsonl`).

Also drawn on: live capture from this build session itself (`PostToolBatch`,
`ConfigChange` observed organically) and a second concurrent `claude -p`
session used to test cross-session isolation (not preserved as a fixture).

## Open questions from the design doc — resolved

**1. Tool-call correlation id (section 11, item 1): CONFIRMED to exist.**
`tool_use_id` is present on `PreToolUse`, `PostToolUse`, and inside every
entry of `PostToolBatch`'s `tool_calls` array. Pairing should use exact
`tool_use_id` matching as the primary strategy — the FIFO/hash(`tool_input`)
fallback from the design doc is no longer needed for the common case, but
worth keeping as a defensive fallback for the (unobserved so far, but
undocumented) case of a missing id.

**3. Subagent attribution: CONFIRMED.** `agent_id`/`agent_type` are present
on every event fired inside a subagent's execution — including `SubagentStart`
and `SubagentStop` themselves, which are emitted *with* `agent_id` already
set, not as parent-session events. From the parent's own timeline, launching
a subagent looks like an ordinary tool call: `PreToolUse`/`PostToolUse` with
`tool_name: "Agent"` and a `tool_input` containing `subagent_type`, `prompt`,
`description`. This confirms the file-per-actor routing (design doc 3.1) is
correct as designed: a subagent's own file receives `SubagentStart`, its tool
calls, and `SubagentStop`; the parent's file only sees the wrapping
`Agent` tool call.

**6. Real payload sizes:** not yet measured at scale (small fixtures only);
still open, revisit once more real usage accumulates.

**8. Host-side timestamp: CONFIRMED absent.** No field resembling a
courier-independent timestamp appears in any captured payload. This means
the causality-aware pairing fix (design doc section 3 — order a matched
Pre/Post pair by event type, not by comparing `bb_ts`) is necessary, not
optional: `bb_ts` really is the only timestamp available, and it really is
measured after whatever scheduling delay the courier picked up.

**9. `agent_id` filesystem-safety: CONFIRMED safe.** Observed values are
short lowercase hex-like strings (e.g. `a0ba1fb5d83100135`,
`aa847f7e35d390c61`) — no sanitization issues hit in practice. The defensive
sanitizer in `emit.py` stays as cheap insurance regardless.

## New findings, not anticipated by the design doc

**`PostToolUse` carries `duration_ms`, computed by Claude Code itself.**
This changes the pairing design in a good way: the causality-ordering fix
(section 3) is still needed to decide *when* to swap a spinner to a
checkmark and in what order events render, but the duration *number* shown
in the UI should come straight from `duration_ms` on the `Post` event rather
than being derived from `bb_ts(post) - bb_ts(pre)`. Use the courier-timestamp
delta only as a fallback if `duration_ms` is ever absent.

**`PostToolBatch` is a self-contained summary of the whole batch, not just a
completion marker.** Its `tool_calls` array carries `tool_use_id`,
`tool_name`, `tool_input`, *and* `tool_response` for every call in the batch
— effectively a second, redundant source of the same pairing data. This
matters because of the next finding:

**A permission-denied tool call gets no individual `PostToolUse`,
`PostToolUseFailure`, or `PermissionDenied` event.** In
`missing_post_on_failed_read`, a `Read` outside the session's allowed
directory produced `PreToolUse` → `PostToolBatch` with nothing in between —
no `Post` for that specific `tool_use_id`. The denial is only visible as a
plain-language string inside `PostToolBatch.tool_calls[].tool_response`
("Claude requested permissions to read from ..., but you haven't granted it
yet."). **Implication for `pairing.py`:** before treating an open
`PreToolUse` as "still running," check whether a later `PostToolBatch`
already contains that `tool_use_id` — if so, resolve the pair from the batch
event instead of waiting indefinitely for a `Post` that will never come.
This also means `PostToolUseFailure` and `PermissionDenied` may be rarer in
practice than the design doc assumed (at least in non-interactive `-p` mode
with default permissions) — worth re-checking against an interactive session
where a human is actually prompted to approve/deny, which behaves
differently from the auto-deny seen here.

## Field inventory by event

| Event | Fields observed |
|---|---|
| `SessionStart` | `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `source` (`"startup"` observed; design doc also expects `"resume"`) |
| `UserPromptSubmit` | + `prompt_id`, `permission_mode`, `prompt` |
| `PreToolUse` | + `effort.level`, `tool_name`, `tool_input`, `tool_use_id`, (`agent_id`, `agent_type` if inside a subagent) |
| `PostToolUse` | same as `PreToolUse` + `tool_response`, `duration_ms` |
| `PostToolBatch` | `session_id`, `transcript_path`, `cwd`, `tool_calls: [{tool_name, tool_input, tool_use_id, tool_response}, ...]` |
| `SubagentStart` | `session_id`, `agent_id`, `agent_type`, `agent_transcript_path` |
| `SubagentStop` | + `stop_hook_active`, `last_assistant_message`, `background_tasks`, `session_crons` |
| `ConfigChange` | fired live when `~/.claude/settings.json` was edited mid-session (observed organically, not in a curated fixture) |

Not yet captured/confirmed live: `SessionEnd`, `Stop`, `StopFailure`,
`PostToolUseFailure`, `PermissionRequest`, `PermissionDenied` (denial
observed but without the dedicated event — see above), `PreCompact`,
`PostCompact`, `Notification`, `CwdChanged`. These remain generically
rendered per design principle 4 until captured.

## Still open

- **Session identity across `--resume`/`--continue`/`/clear`** (design doc
  open question 5): not tested this pass.
- **Real payload size distribution** for setting the truncation ceiling
  precisely (open question 6).
- **`PermissionRequest`/`PermissionDenied` in an actual interactive session**
  (a human approving/denying live) — the auto-deny behavior seen in `-p`
  mode may not represent the interactive path at all.

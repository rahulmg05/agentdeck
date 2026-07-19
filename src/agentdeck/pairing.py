"""Pre/Post tool-call correlation and turn grouping.

Pairing strategy (design doc section 11, refined by docs/payloads.md's real
fixture findings): `tool_use_id` is a real, stable correlation id — use it
directly, no FIFO/hash fallback needed for the common case. Order within a
pair is derived from event type (`Pre` is always first by construction),
never from comparing `ad_ts` — courier-measured timestamps can occasionally
invert under scheduling load (design doc section 3), but which event
*started* the pair is never in question. Duration comes from `PostToolUse`'s
own `duration_ms` field when present (Claude Code computes it itself); only
fall back to a `ad_ts` delta, clamped at zero, if `duration_ms` is missing.

A tool call can also resolve via `PostToolBatch` instead of an individual
`PostToolUse` — observed for permission-denied calls, which get no
individual Post event at all (docs/payloads.md). Treating an open PreToolUse
as "still running" forever in that case would be wrong, so PostToolBatch is
checked as a second resolution path.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agentdeck.events import Event


class ToolCallStatus(Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


@dataclass
class ToolCall:
    tool_use_id: str
    session_id: str
    agent_id: str | None
    tool_name: str
    tool_input: dict[str, Any]
    pre_event: Event
    status: ToolCallStatus = ToolCallStatus.PENDING
    tool_response: Any = None
    duration_ms: float | None = None
    post_ad_ts: float | None = None

    @property
    def actor_key(self) -> tuple[str, str | None]:
        return (self.session_id, self.agent_id)


def _fallback_duration_ms(call: ToolCall, post_ad_ts: float) -> float:
    return max(0.0, (post_ad_ts - call.pre_event.ad_ts) * 1000)


class PairTracker:
    """Feed it events as they arrive (any order tolerated); it maintains the
    set of open/resolved tool calls. `tool_use_id` is assumed globally
    unique (an Anthropic API tool-call id), so no per-actor scoping is
    needed on the lookup key.
    """

    def __init__(self) -> None:
        self._open: dict[str, ToolCall] = {}
        self.resolved: list[ToolCall] = []

    def observe(self, event: Event) -> ToolCall | list[ToolCall] | None:
        """Returns the ToolCall(s) this event affected, if any."""
        name = event.hook_event_name

        if name == "PreToolUse" and event.tool_use_id:
            call = ToolCall(
                tool_use_id=event.tool_use_id,
                session_id=event.session_id,
                agent_id=event.agent_id,
                tool_name=event.tool_name or "?",
                tool_input=event.raw.get("tool_input") or {},
                pre_event=event,
            )
            self._open[event.tool_use_id] = call
            return call

        if name in ("PostToolUse", "PostToolUseFailure") and event.tool_use_id:
            call = self._open.pop(event.tool_use_id, None)
            if call is None:
                return None
            call.status = (
                ToolCallStatus.FAILED if name == "PostToolUseFailure" else ToolCallStatus.DONE
            )
            call.tool_response = event.raw.get("tool_response")
            duration = event.raw.get("duration_ms")
            call.duration_ms = (
                float(duration)
                if isinstance(duration, (int, float))
                else _fallback_duration_ms(call, event.ad_ts)
            )
            call.post_ad_ts = event.ad_ts
            self.resolved.append(call)
            return call

        if name == "PostToolBatch":
            resolved: list[ToolCall] = []
            for tc in event.raw.get("tool_calls") or []:
                tool_use_id = tc.get("tool_use_id")
                if not tool_use_id:
                    continue
                call = self._open.pop(tool_use_id, None)
                if call is None:
                    # Already resolved individually, or opened before this
                    # tracker started observing — nothing to do.
                    continue
                call.status = ToolCallStatus.DONE
                call.tool_response = tc.get("tool_response")
                call.duration_ms = _fallback_duration_ms(call, event.ad_ts)
                call.post_ad_ts = event.ad_ts
                resolved.append(call)
                self.resolved.append(call)
            return resolved or None

        return None

    def open_calls(self) -> list[ToolCall]:
        return list(self._open.values())

    def get(self, tool_use_id: str) -> ToolCall | None:
        for call in self._open.values():
            if call.tool_use_id == tool_use_id:
                return call
        for call in self.resolved:
            if call.tool_use_id == tool_use_id:
                return call
        return None


@dataclass
class Turn:
    """Events grouped under the UserPromptSubmit that started them (design
    doc Phase 4: "Turn grouping: events nested under their UserPromptSubmit,
    collapsible"). Scoped per actor — a subagent's tool calls happen inside
    its own turn structure, initiated by its own SubagentStart, not the
    parent's UserPromptSubmit.
    """

    prompt_event: Event | None
    events: list[Event] = field(default_factory=list)


class TurnGrouper:
    """Groups a per-actor event stream into turns. One instance per actor
    (session_id, agent_id) — turns don't span actors."""

    def __init__(self) -> None:
        self.turns: list[Turn] = []
        self._current: Turn | None = None

    def observe(self, event: Event) -> None:
        if event.hook_event_name in ("UserPromptSubmit", "SubagentStart"):
            self._current = Turn(prompt_event=event, events=[event])
            self.turns.append(self._current)
            return

        if self._current is None:
            self._current = Turn(prompt_event=None, events=[])
            self.turns.append(self._current)
        self._current.events.append(event)

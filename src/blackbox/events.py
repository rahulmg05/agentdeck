"""Envelope/payload parsing into typed Event objects, plus the session
registry derived from a stream of events. Tolerant of schema drift (design
doc principle 4): unknown fields are ignored, missing ones never crash
parsing, and unrecognized events still produce a renderable Event.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Design doc section 3.1: assign color by hashing session_id into a fixed
# palette, never by arrival order, so colors are stable across restarts.
# Python's builtin hash() is randomized per-process for strings, so we use
# a stable hash (sha256) instead.
_PALETTE = [
    "#e06c75",
    "#98c379",
    "#e5c07b",
    "#61afef",
    "#c678dd",
    "#56b6c2",
    "#d19a66",
    "#ff6b9d",
    "#528bff",
    "#8abeb7",
    "#b5bd68",
    "#cc99cc",
]


def stable_color(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).digest()
    return _PALETTE[digest[0] % len(_PALETTE)]


# Events understood to mark liveness/failure for session-registry bookkeeping.
FAILURE_EVENTS = {"PostToolUseFailure", "StopFailure"}


@dataclass
class Event:
    bb_schema: int
    bb_ts: float
    bb_host_pid: int
    bb_truncated: bool
    session_id: str
    agent_id: str | None
    hook_event_name: str
    raw: dict[str, Any]
    source_file: Path

    @property
    def tool_name(self) -> str | None:
        return self.raw.get("tool_name")

    @property
    def tool_use_id(self) -> str | None:
        return self.raw.get("tool_use_id")

    @property
    def cwd(self) -> str | None:
        return self.raw.get("cwd")


def parse_line(line: str, source_file: Path) -> Event | None:
    """Parse one JSONL line into an Event, or None if it's unparseable (the
    caller should count that toward a "dropped lines" stat, not crash)."""
    line = line.strip()
    if not line:
        return None
    try:
        envelope = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict):
        return None

    event = envelope.get("event")
    if not isinstance(event, dict):
        event = {}

    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        session_id = source_file.parent.name

    bb_ts = envelope.get("bb_ts")
    if not isinstance(bb_ts, (int, float)):
        bb_ts = 0.0

    return Event(
        bb_schema=envelope.get("bb_schema", 0),
        bb_ts=float(bb_ts),
        bb_host_pid=envelope.get("bb_host_pid", 0),
        bb_truncated=bool(envelope.get("bb_truncated", False)),
        session_id=session_id,
        agent_id=event.get("agent_id"),
        hook_event_name=event.get("hook_event_name", "Unknown"),
        raw=event,
        source_file=source_file,
    )


@dataclass
class SessionInfo:
    session_id: str
    cwd: str | None = None
    color: str = "#ffffff"
    # Dual-color system (feature-parity item): "app" (project) color is a
    # second, coarser dimension distinct from the per-session color — every
    # session running in the same project shares an app color, so multiple
    # concurrent sessions in one repo are visually grouped, while each still
    # keeps its own distinct session color.
    app_color: str = "#ffffff"
    ended: bool = False
    first_event_ts: float = float("inf")
    last_event_ts: float = 0.0
    tool_count: int = 0
    fail_count: int = 0
    turn_count: int = 0
    agent_ids: set[str] = field(default_factory=set)
    transcript_path: str | None = None

    # Phase 5: token/cost tracking, populated from transcript.py's usage
    # entries via SessionRegistry.add_usage() — not derived from hook events.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    # minute-epoch -> tokens added in that minute, for a tokens/min sparkline
    token_minute_buckets: dict[int, int] = field(default_factory=dict)


class SessionRegistry:
    """Derives per-session display state from the event stream. Pure
    bookkeeping — never reaches back into the filesystem, so it's identical
    whether events arrive from live tailing or from static history replay.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}

    def observe(self, event: Event) -> SessionInfo:
        info = self._sessions.get(event.session_id)
        if info is None:
            info = SessionInfo(session_id=event.session_id, color=stable_color(event.session_id))
            self._sessions[event.session_id] = info

        if event.cwd:
            info.cwd = event.cwd
            info.app_color = stable_color(Path(event.cwd).name)
        if event.raw.get("transcript_path"):
            info.transcript_path = event.raw["transcript_path"]
        info.last_event_ts = max(info.last_event_ts, event.bb_ts)
        info.first_event_ts = min(info.first_event_ts, event.bb_ts)
        if event.agent_id:
            info.agent_ids.add(event.agent_id)

        if event.hook_event_name == "SessionEnd":
            info.ended = True
        if event.hook_event_name == "PreToolUse":
            info.tool_count += 1
        if event.hook_event_name in FAILURE_EVENTS:
            info.fail_count += 1
        if event.hook_event_name == "UserPromptSubmit":
            info.turn_count += 1

        return info

    def get(self, session_id: str) -> SessionInfo | None:
        return self._sessions.get(session_id)

    def all_sessions(self) -> list[SessionInfo]:
        return list(self._sessions.values())

    def display_name(self, session_id: str) -> str:
        info = self._sessions.get(session_id)
        if not info or not info.cwd:
            return session_id[:8]

        basename = Path(info.cwd).name
        colliding = [
            s
            for s in self._sessions.values()
            if s.cwd and Path(s.cwd).name == basename and s.session_id != session_id
        ]
        if colliding:
            return f"{basename}-{session_id[:4]}"
        return basename

    def liveness(self, session_id: str, now: float, running_window_s: float = 60.0) -> str:
        info = self._sessions.get(session_id)
        if info is None:
            return "idle"
        if info.ended:
            return "ended"
        if now - info.last_event_ts < running_window_s:
            return "running"
        return "idle"

    def add_usage(self, session_id: str, input_tokens: int, output_tokens: int,
                  cache_write_tokens: int, cache_read_tokens: int, cost_usd: float,
                  bucket_now: float) -> None:
        """Record token/cost usage for a session (design doc Phase 5). Driven
        by transcript.py's usage entries, not by hook events, so a session
        may not exist yet if usage arrives before any hook event has — create
        it defensively rather than dropping the data."""
        info = self._sessions.get(session_id)
        if info is None:
            info = SessionInfo(session_id=session_id, color=stable_color(session_id))
            self._sessions[session_id] = info

        info.input_tokens += input_tokens
        info.output_tokens += output_tokens
        info.cache_write_tokens += cache_write_tokens
        info.cache_read_tokens += cache_read_tokens
        info.cost_usd += cost_usd

        minute = int(bucket_now // 60)
        total_tokens = input_tokens + output_tokens + cache_write_tokens + cache_read_tokens
        info.token_minute_buckets[minute] = info.token_minute_buckets.get(minute, 0) + total_tokens

    def tokens_per_minute_series(self, session_id: str, now: float, window_minutes: int = 20) -> list[float]:
        info = self._sessions.get(session_id)
        if info is None:
            return [0.0] * window_minutes
        current_minute = int(now // 60)
        return [
            float(info.token_minute_buckets.get(current_minute - window_minutes + 1 + i, 0))
            for i in range(window_minutes)
        ]

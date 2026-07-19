"""Discovers session directories under a sessions root, tails each file
(watchfiles), tracks a byte offset per file, and merges the resulting events
across files by ad_ts (design doc section 2/3.1: file-per-actor means the
console must watch a directory tree and merge streams, not tail one file).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from watchfiles import Change, awatch

from agentdeck.events import Event, SessionRegistry, parse_line
from agentdeck.paths import SESSIONS_DIR as DEFAULT_SESSIONS_DIR
from agentdeck.pricing import estimate_cost_usd
from agentdeck.transcript import TranscriptReader


class Reader:
    def __init__(self, sessions_dir: Path = DEFAULT_SESSIONS_DIR) -> None:
        self.sessions_dir = sessions_dir
        self._offsets: dict[Path, int] = {}
        self.dropped_lines = 0

    def _discover_files(self) -> list[Path]:
        if not self.sessions_dir.exists():
            return []
        return sorted(self.sessions_dir.glob("*/*.jsonl"))

    def _read_new_lines(self, path: Path) -> list[Event]:
        # Normalize to a resolved path before touching self._offsets:
        # watchfiles.awatch() reports OS-resolved paths (symlinks followed,
        # e.g. macOS's /var -> /private/var), while glob() in
        # _discover_files() returns paths in whatever form sessions_dir was
        # constructed with. If those two forms don't match as dict keys,
        # every watch()-triggered read for a file silently misses its
        # load_history()-established offset and starts over from 0 —
        # replaying and duplicating the *entire* file's history into the
        # live stream (which also double-counts cost/tokens downstream).
        path = path.resolve()
        try:
            size = path.stat().st_size
        except OSError:
            return []

        offset = self._offsets.get(path, 0)
        if size < offset:
            # File shrank — most likely rotated out from under us. Start over.
            offset = 0
        if size == offset:
            return []

        events: list[Event] = []
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
            self._offsets[path] = offset + len(chunk)

        for raw_line in chunk.decode("utf-8", errors="replace").splitlines():
            if not raw_line.strip():
                continue
            event = parse_line(raw_line, path)
            if event is None:
                self.dropped_lines += 1
            else:
                events.append(event)
        return events

    def load_history(self) -> list[Event]:
        """Read all existing session files from the start, sorted by ad_ts."""
        events: list[Event] = []
        for path in self._discover_files():
            events.extend(self._read_new_lines(path))
        events.sort(key=lambda e: e.ad_ts)
        return events

    async def watch(self) -> AsyncIterator[Event]:
        """Yield newly appended events as they land, merged by ad_ts within
        each batch of filesystem-change notifications."""
        if not self.sessions_dir.exists():
            self.sessions_dir.mkdir(parents=True, exist_ok=True)

        async for changes in awatch(self.sessions_dir, recursive=True):
            batch: list[Event] = []
            seen_paths = set()
            for change_type, changed_path in changes:
                path = Path(changed_path)
                if path.suffix != ".jsonl" or path in seen_paths:
                    continue
                seen_paths.add(path)
                if change_type == Change.deleted:
                    self._offsets.pop(path, None)
                    continue
                batch.extend(self._read_new_lines(path))

            batch.sort(key=lambda e: e.ad_ts)
            for event in batch:
                yield event


@dataclass
class SessionSummary:
    session_id: str
    display_name: str
    started_at: float | None
    ended_at: float | None
    fail_count: int
    cost_usd: float
    event_count: int


def load_session_events(session_dir: Path) -> list[Event]:
    """One-shot, non-incremental read of every file in a single session
    directory — for replay/browse, which need the whole history at once
    rather than Reader's live-tailing offset machinery."""
    events: list[Event] = []
    for jsonl_file in sorted(session_dir.glob("*.jsonl")):
        for raw_line in jsonl_file.read_text(errors="replace").splitlines():
            if not raw_line.strip():
                continue
            event = parse_line(raw_line, jsonl_file)
            if event is not None:
                events.append(event)
    events.sort(key=lambda e: e.ad_ts)
    return events


def scan_sessions(sessions_dir: Path, pricing: dict) -> list[SessionSummary]:
    """Lightweight summary of every session directory, for the session
    browser (design doc Phase 6)."""
    if not sessions_dir.exists():
        return []

    summaries = []
    for session_dir in sorted(p for p in sessions_dir.iterdir() if p.is_dir()):
        events = load_session_events(session_dir)
        if not events:
            continue

        registry = SessionRegistry()
        for event in events:
            registry.observe(event)
        # A session directory's name is its session_id in production
        # (~/.agentdeck/sessions/<session_id>/), but don't assume that here —
        # look up whichever session the events themselves report, since
        # fixture/test directories are free to use descriptive names instead.
        sessions_seen = registry.all_sessions()
        if not sessions_seen:
            continue
        info = sessions_seen[0]

        cost = 0.0
        if info.transcript_path:
            transcript_reader = TranscriptReader(Path(info.transcript_path))
            for usage in transcript_reader.read_new_usage():
                cost += estimate_cost_usd(usage, pricing)

        summaries.append(
            SessionSummary(
                session_id=session_dir.name,
                display_name=registry.display_name(info.session_id),
                started_at=info.first_event_ts if info.first_event_ts != float("inf") else None,
                ended_at=info.last_event_ts or None,
                fail_count=info.fail_count,
                cost_usd=cost,
                event_count=len(events),
            )
        )

    summaries.sort(key=lambda s: s.started_at or 0, reverse=True)
    return summaries

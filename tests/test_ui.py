"""Headless tests of the Textual app via Textual's Pilot test harness — no
real terminal needed. Exercises the actual app runtime, not just the
underlying reader/events logic tested elsewhere.
"""

import asyncio
import json
import time
from pathlib import Path

import pytest
from textual.widgets import RichLog, Static

from agentdeck.events import stable_color
from agentdeck.ui.app import AgentDeckApp

FIXTURES = Path(__file__).parent / "fixtures"


def count_fixture_lines() -> int:
    return sum(1 for f in FIXTURES.rglob("*.jsonl") for _ in f.read_text().splitlines() if _)


def write_event(path: Path, session_id: str, hook_event_name: str, ts: float, **extra) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "ad_schema": 1,
        "ad_ts": ts,
        "ad_seq": 0,
        "ad_host_pid": 1,
        "event": {"session_id": session_id, "hook_event_name": hook_event_name, **extra},
    }
    with open(path, "a") as f:
        f.write(json.dumps(envelope) + "\n")


def test_stable_color_is_deterministic_not_hash_randomized():
    # A real risk: Python's builtin hash() is randomized per-process for
    # strings, which would make colors reshuffle across restarts (design doc
    # 3.1 explicitly requires stability). sha256-based stable_color must not
    # depend on that.
    assert stable_color("session-abc") == stable_color("session-abc")

    import hashlib

    expected_digest = hashlib.sha256(b"session-abc").digest()[0]
    color = stable_color("session-abc")
    from agentdeck.events import _PALETTE

    assert color == _PALETTE[expected_digest % len(_PALETTE)]


@pytest.mark.asyncio
async def test_loads_history_from_fixtures():
    app = AgentDeckApp(sessions_dir=FIXTURES)
    async with app.run_test() as pilot:
        assert app.event_count == count_fixture_lines()
        # firehose is hidden (not laid out) unless selected — RichLog defers
        # rendering until it has a real size, so switch modes before reading.
        await pilot.press("f")
        await pilot.pause()
        log = app.query_one("#timeline", RichLog)
        assert len(log.lines) > 0


@pytest.mark.asyncio
async def test_stats_bar_shows_session_count():
    app = AgentDeckApp(sessions_dir=FIXTURES)
    async with app.run_test():
        stats_text = str(app.query_one("#stats", Static).content)
        assert "events:" in stats_text
        assert "sessions:" in stats_text
        # 3 fixture dirs = 3 distinct session_ids
        assert "sessions: 3" in stats_text


@pytest.mark.asyncio
async def test_clear_keybinding_empties_view(pilot_tmp_path=None):
    app = AgentDeckApp(sessions_dir=FIXTURES)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()
        log = app.query_one("#timeline", RichLog)
        assert len(log.lines) > 0
        await pilot.press("c")
        assert len(log.lines) == 0
        # underlying state is untouched by a view-only clear
        assert app.event_count == count_fixture_lines()


@pytest.mark.asyncio
async def test_live_tail_picks_up_new_event(tmp_path):
    session_dir = tmp_path / "sess-live"
    write_event(session_dir / "main.jsonl", "sess-live", "SessionStart", time.time())

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()
        assert app.event_count == 1

        write_event(session_dir / "main.jsonl", "sess-live", "PreToolUse", time.time(), tool_name="Bash")
        await asyncio.sleep(0.6)
        await pilot.pause()

        assert app.event_count == 2
        log = app.query_one("#timeline", RichLog)
        assert len(log.lines) == 2


@pytest.mark.asyncio
async def test_pause_freezes_view_but_not_bookkeeping(tmp_path):
    session_dir = tmp_path / "sess-live"
    write_event(session_dir / "main.jsonl", "sess-live", "SessionStart", time.time())

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()
        log = app.query_one("#timeline", RichLog)
        lines_before_pause = len(log.lines)

        await pilot.press("p")
        assert app.paused is True

        write_event(session_dir / "main.jsonl", "sess-live", "PreToolUse", time.time(), tool_name="Bash")
        await asyncio.sleep(0.6)
        await pilot.pause()

        # bookkeeping (count, registry, buffer) keeps moving...
        assert app.event_count == 2
        # ...but the visible log does not, while paused.
        assert len(log.lines) == lines_before_pause

        await pilot.press("p")
        assert app.paused is False
        # unpausing flushes what accumulated while paused
        assert len(log.lines) == 2


@pytest.mark.asyncio
async def test_scroll_down_pauses_autoscroll_end_resumes(tmp_path):
    # Newest-first: the log is anchored at the TOP (y=0), not the bottom —
    # so "scrolled away from the latest" now means scrolling DOWN into
    # older history, not up.
    session_dir = tmp_path / "sess-live"
    for i in range(40):
        write_event(session_dir / "main.jsonl", "sess-live", "PreToolUse", 100.0 + i, tool_name="Bash")

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        # RichLog defers rendering until its size is known (see its own
        # docstring) — give layout a tick to settle before reading/setting
        # scroll position, otherwise scroll_y/max_scroll_y are still zeroed.
        # It's also hidden unless firehose mode is active, which likewise
        # prevents it from ever being sized.
        await pilot.press("f")
        await pilot.pause()

        log = app.query_one("#timeline", RichLog)
        assert log.auto_scroll is True
        assert log.scroll_y == 0  # anchored at top (newest) by default

        # simulate the user manually scrolling down into older history
        log.scroll_to(y=log.max_scroll_y, animate=False)
        await pilot.pause()
        assert log.auto_scroll is False

        write_event(session_dir / "main.jsonl", "sess-live", "PreToolUse", 200.0, tool_name="Bash")
        await asyncio.sleep(0.6)
        await pilot.pause()
        # new events still get recorded, but the view didn't jump the user
        # back to the top while they were scrolled down into history
        assert app.event_count == 41
        assert log.auto_scroll is False

        await pilot.press("end")
        assert log.auto_scroll is True
        assert log.scroll_y == 0


@pytest.mark.asyncio
async def test_filter_by_session_number(tmp_path):
    write_event(tmp_path / "sess-a" / "main.jsonl", "sess-a", "SessionStart", 100.0)
    write_event(tmp_path / "sess-a" / "main.jsonl", "sess-a", "PreToolUse", 101.0, tool_name="Bash")
    write_event(tmp_path / "sess-b" / "main.jsonl", "sess-b", "SessionStart", 100.5)

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()
        assert app.event_count == 3
        log = app.query_one("#timeline", RichLog)
        assert len(log.lines) == 3

        await pilot.press("1")
        # session "a" started first chronologically (ad_ts 100.0 < 100.5) so
        # it should be filter slot 1
        assert len(log.lines) == 2

        await pilot.press("0")
        assert len(log.lines) == 3

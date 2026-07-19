"""Verifies events render newest-first (most recent at the top) in every
view — firehose, focused mode, and wall panes — for both bulk loads
(initial history, mode/filter rebuilds) and live incremental updates."""

import asyncio
import json
from pathlib import Path

import pytest
from textual.widgets import RichLog

from blackbox.ui.app import BlackboxApp
from blackbox.ui.widgets.focused_timeline import FocusedTimeline


def write_event(path: Path, session_id: str, hook_event_name: str, ts: float, **extra) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "bb_schema": 1,
        "bb_ts": ts,
        "bb_seq": 0,
        "bb_host_pid": 1,
        "event": {"session_id": session_id, "hook_event_name": hook_event_name, **extra},
    }
    with open(path, "a") as f:
        f.write(json.dumps(envelope) + "\n")


def _line_text(strip) -> str:
    return "".join(seg.text for seg in strip)


@pytest.mark.asyncio
async def test_firehose_bulk_load_shows_newest_at_top(tmp_path):
    session_dir = tmp_path / "sess-1"
    for i in range(5):
        write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 100.0 + i, tool_name=f"Tool{i}")

    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()
        log = app.query_one("#timeline", RichLog)

        assert "Tool4" in _line_text(log.lines[0])  # newest (last written) is first
        assert "Tool0" in _line_text(log.lines[-1])  # oldest is last


@pytest.mark.asyncio
async def test_firehose_live_event_inserted_at_top(tmp_path):
    session_dir = tmp_path / "sess-1"
    write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 100.0, tool_name="First")

    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 101.0, tool_name="Second")
        await asyncio.sleep(0.6)
        await pilot.pause()

        log = app.query_one("#timeline", RichLog)
        assert "Second" in _line_text(log.lines[0])
        assert "First" in _line_text(log.lines[1])


@pytest.mark.asyncio
async def test_firehose_stays_anchored_to_top_across_several_live_events(tmp_path):
    session_dir = tmp_path / "sess-1"
    write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 100.0, tool_name="E0")

    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        for i in range(1, 6):
            write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 100.0 + i, tool_name=f"E{i}")
            await asyncio.sleep(0.15)
        await pilot.pause()

        log = app.query_one("#timeline", RichLog)
        # newest-to-oldest, top-to-bottom
        for i, expected in enumerate(["E5", "E4", "E3", "E2", "E1", "E0"]):
            assert expected in _line_text(log.lines[i])


@pytest.mark.asyncio
async def test_focused_timeline_bulk_load_shows_newest_at_top(tmp_path):
    session_dir = tmp_path / "sess-1"
    for i in range(5):
        write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 100.0 + i, tool_name=f"Tool{i}", tool_use_id=f"t{i}")

    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test():
        table = app.query_one("#focused-timeline", FocusedTimeline)
        top_row = table.get_row_at(0)
        bottom_row = table.get_row_at(table.row_count - 1)
        assert "Tool4" in str(top_row)
        assert "Tool0" in str(bottom_row)


@pytest.mark.asyncio
async def test_focused_timeline_live_event_inserted_at_top(tmp_path):
    session_dir = tmp_path / "sess-1"
    write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 100.0, tool_name="First", tool_use_id="t0")

    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 101.0, tool_name="Second", tool_use_id="t1")
        await asyncio.sleep(0.6)
        await pilot.pause()

        table = app.query_one("#focused-timeline", FocusedTimeline)
        assert "Second" in str(table.get_row_at(0))
        assert "First" in str(table.get_row_at(1))


@pytest.mark.asyncio
async def test_wall_pane_bulk_load_shows_newest_at_top(tmp_path):
    session_dir = tmp_path / "sess-1"
    for i in range(4):
        write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 100.0 + i, tool_name=f"Tool{i}")

    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("w")
        await pilot.pause()

        pane = app._wall_panes["sess-1"]
        assert "Tool3" in _line_text(pane.lines[0])
        assert "Tool0" in _line_text(pane.lines[-1])


@pytest.mark.asyncio
async def test_wall_pane_live_event_inserted_at_top(tmp_path):
    session_dir = tmp_path / "sess-1"
    write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 100.0, tool_name="First")

    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("w")
        await pilot.pause()

        write_event(session_dir / "main.jsonl", "sess-1", "PreToolUse", 101.0, tool_name="Second")
        await asyncio.sleep(0.6)
        await pilot.pause()

        pane = app._wall_panes["sess-1"]
        assert "Second" in _line_text(pane.lines[0])
        assert "First" in _line_text(pane.lines[1])


@pytest.mark.asyncio
async def test_replay_seek_preserves_newest_first_order(tmp_path):
    from blackbox.events import parse_line

    events = []
    for i in range(10):
        line = json.dumps(
            {
                "bb_schema": 1, "bb_ts": 100.0 + i, "bb_seq": 0, "bb_host_pid": 1,
                "event": {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": f"T{i}", "tool_use_id": f"t{i}"},
            }
        )
        events.append(parse_line(line, Path("s/main.jsonl")))

    app = BlackboxApp(replay_events=events)
    async with app.run_test() as pilot:
        await pilot.press("space")  # pause immediately
        await asyncio.sleep(0.1)
        app._replay_jump_to(6)
        await pilot.press("f")
        await pilot.pause()

        log = app.query_one("#timeline", RichLog)
        assert "T5" in _line_text(log.lines[0])  # 6th event (index 5) is newest so far
        assert "T0" in _line_text(log.lines[-1])

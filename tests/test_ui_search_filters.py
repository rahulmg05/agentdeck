"""Phase 7 tests: search, event-type/errors-only filters, and the command
palette's custom commands."""

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


def make_mixed_session(tmp_path: Path) -> Path:
    p = tmp_path / "sess-1" / "main.jsonl"
    write_event(p, "sess-1", "SessionStart", 100.0)
    write_event(p, "sess-1", "PreToolUse", 101.0, tool_name="Bash", tool_use_id="t1", tool_input={"command": "echo hello"})
    write_event(p, "sess-1", "PostToolUse", 101.5, tool_name="Bash", tool_use_id="t1")
    write_event(p, "sess-1", "PreToolUse", 102.0, tool_name="Read", tool_use_id="t2", tool_input={"file_path": "/x/y.txt"})
    write_event(p, "sess-1", "PostToolUseFailure", 102.5, tool_name="Read", tool_use_id="t2")
    return tmp_path


@pytest.mark.asyncio
async def test_errors_only_filter_hides_non_failure_events(tmp_path):
    make_mixed_session(tmp_path)
    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()
        log = app.query_one("#timeline", RichLog)
        lines_before = len(log.lines)
        assert lines_before == 5

        await pilot.press("e")
        assert app.errors_only is True
        assert len(log.lines) == 1  # only PostToolUseFailure

        await pilot.press("e")
        assert len(log.lines) == lines_before


@pytest.mark.asyncio
async def test_event_type_filter_via_command_palette_helper(tmp_path):
    make_mixed_session(tmp_path)
    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        app.set_event_type_filter("PreToolUse")
        log = app.query_one("#timeline", RichLog)
        assert len(log.lines) == 2  # the two PreToolUse events

        app.set_event_type_filter(None)
        assert len(log.lines) == 5


@pytest.mark.asyncio
async def test_search_matches_tool_input_content(tmp_path):
    make_mixed_session(tmp_path)
    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        app.search_query = "echo hello"
        app._apply_filters_everywhere()

        log = app.query_one("#timeline", RichLog)
        assert len(log.lines) == 1  # only the Bash PreToolUse mentions "echo hello"


@pytest.mark.asyncio
async def test_search_is_case_insensitive(tmp_path):
    make_mixed_session(tmp_path)
    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        app.search_query = "ECHO"
        app._apply_filters_everywhere()

        log = app.query_one("#timeline", RichLog)
        assert len(log.lines) == 1


@pytest.mark.asyncio
async def test_filters_do_not_affect_underlying_bookkeeping(tmp_path):
    make_mixed_session(tmp_path)
    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("e")
        await pilot.pause()
        # errors_only hides most events from the view, but the registry
        # must still have counted everything
        assert app.event_count == 5
        info = app.registry.get("sess-1")
        assert info.tool_count == 2


@pytest.mark.asyncio
async def test_filters_apply_to_focused_timeline_too(tmp_path):
    make_mixed_session(tmp_path)
    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("e")
        await pilot.pause()
        table = app.query_one("#focused-timeline", FocusedTimeline)
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_command_palette_includes_mode_and_session_commands(tmp_path):
    make_mixed_session(tmp_path)
    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test():
        commands = list(app.get_system_commands(app.screen))
        titles = [c.title for c in commands]
        assert "Mode: firehose" in titles
        assert "Mode: wall" in titles
        assert "Toggle pause" in titles
        assert any(t.startswith("Jump to session:") for t in titles)
        assert any(t.startswith("Filter: ") for t in titles)


@pytest.mark.asyncio
async def test_jump_to_session_command_selects_and_switches_to_focused(tmp_path):
    write_event(tmp_path / "sess-a" / "main.jsonl", "sess-a", "SessionStart", 100.0)
    write_event(tmp_path / "sess-b" / "main.jsonl", "sess-b", "SessionStart", 101.0)

    app = BlackboxApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("w")
        assert app.mode == "wall"

        app._jump_to_session("sess-a")
        assert app.mode == "focused"
        assert app.selected_session_id == "sess-a"
        assert app.focus_follow is False

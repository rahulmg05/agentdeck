"""Phase 4 cockpit layout tests: modes, sidebar, focused timeline,
focus-follow, wall tiling, and the detail view."""

import asyncio
import json
from pathlib import Path

import pytest

from agentdeck.ui.app import AgentDeckApp
from agentdeck.ui.widgets.detail_screen import DetailScreen
from agentdeck.ui.widgets.focused_timeline import FocusedTimeline
from agentdeck.ui.widgets.session_sidebar import SessionSidebar


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


def make_sessions_dir(tmp_path: Path, n: int, prefix="sess") -> Path:
    for i in range(n):
        sid = f"{prefix}-{i}"
        write_event(tmp_path / sid / "main.jsonl", sid, "SessionStart", 100.0 + i)
        write_event(tmp_path / sid / "main.jsonl", sid, "PreToolUse", 101.0 + i, tool_name="Bash", tool_use_id=f"t{i}")
    return tmp_path


@pytest.mark.asyncio
async def test_default_mode_is_focused_with_sidebar_and_timeline_visible():
    app = AgentDeckApp(sessions_dir=Path(__file__).parent / "fixtures")
    async with app.run_test():
        assert app.mode == "focused"
        assert app.query_one("#focused-layout").display is True
        assert app.query_one("#timeline").display is False
        assert app.query_one("#wall-layout").display is False


@pytest.mark.asyncio
async def test_mode_switching_preserves_underlying_state(tmp_path):
    make_sessions_dir(tmp_path, 2)
    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        count_before = app.event_count
        await pilot.press("f")
        await pilot.press("w")
        await pilot.press("s")
        assert app.mode == "focused"
        # switching modes must not touch bookkeeping or re-read history
        assert app.event_count == count_before


@pytest.mark.asyncio
async def test_sidebar_lists_all_sessions(tmp_path):
    make_sessions_dir(tmp_path, 3)
    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test():
        sidebar = app.query_one("#sidebar", SessionSidebar)
        assert sidebar.row_count == 3


@pytest.mark.asyncio
async def test_focused_timeline_shows_only_selected_session(tmp_path):
    make_sessions_dir(tmp_path, 2)
    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test():
        table = app.query_one("#focused-timeline", FocusedTimeline)
        # every visible row belongs to the currently selected session
        for key in table._events:
            assert table._events[key].session_id == app.selected_session_id
        assert table.row_count == 2  # SessionStart + PreToolUse for that one session


@pytest.mark.asyncio
async def test_tab_cycles_sessions_and_disables_focus_follow(tmp_path):
    make_sessions_dir(tmp_path, 3)
    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        assert app.focus_follow is True
        first = app.selected_session_id

        await pilot.press("tab")
        assert app.focus_follow is False
        assert app.selected_session_id != first

        await pilot.press("tab")
        await pilot.press("tab")
        # cycled through all 3 and back to the first
        assert app.selected_session_id == first


@pytest.mark.asyncio
async def test_focus_follow_switches_to_newly_active_session(tmp_path):
    session_a = tmp_path / "sess-a"
    write_event(session_a / "main.jsonl", "sess-a", "SessionStart", 100.0)

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        assert app.selected_session_id == "sess-a"

        write_event(tmp_path / "sess-b" / "main.jsonl", "sess-b", "SessionStart", 101.0)
        await asyncio.sleep(0.6)
        await pilot.pause()

        # a new session became active; focus-follow (on by default) should
        # have jumped to it
        assert app.selected_session_id == "sess-b"


@pytest.mark.asyncio
async def test_focus_follow_toggle_key_disables_and_freezes_selection(tmp_path):
    session_a = tmp_path / "sess-a"
    write_event(session_a / "main.jsonl", "sess-a", "SessionStart", 100.0)

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("g")
        assert app.focus_follow is False

        write_event(tmp_path / "sess-b" / "main.jsonl", "sess-b", "SessionStart", 101.0)
        await asyncio.sleep(0.6)
        await pilot.pause()

        # focus-follow was off, so the new session must not steal selection
        assert app.selected_session_id == "sess-a"


@pytest.mark.asyncio
async def test_scrolling_down_in_focused_timeline_disables_focus_follow(tmp_path):
    # Newest-first: the table is anchored at the TOP (y=0), not the bottom —
    # so "scrolled away from the latest" now means scrolling DOWN into
    # older history, not up.
    session_dir = tmp_path / "sess-a"
    for i in range(40):
        write_event(session_dir / "main.jsonl", "sess-a", "PreToolUse", 100.0 + i, tool_name="Bash", tool_use_id=f"t{i}")

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("#focused-timeline", FocusedTimeline)
        assert app.focus_follow is True
        assert table.scroll_y == 0  # anchored at top (newest) by default

        table.scroll_to(y=table.max_scroll_y, animate=False)
        await pilot.pause()
        assert app.focus_follow is False

        # a new session appearing must not steal selection now
        write_event(tmp_path / "sess-b" / "main.jsonl", "sess-b", "SessionStart", 200.0)
        await asyncio.sleep(0.6)
        await pilot.pause()
        assert app.selected_session_id == "sess-a"

        await pilot.press("end")
        assert table.auto_scroll is True
        assert table.scroll_y == 0


@pytest.mark.asyncio
async def test_enter_on_focused_row_opens_detail_screen(tmp_path):
    make_sessions_dir(tmp_path, 1)
    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        table = app.query_one("#focused-timeline", FocusedTimeline)
        table.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, DetailScreen)
        await pilot.press("escape")
        assert not isinstance(app.screen, DetailScreen)


@pytest.mark.asyncio
async def test_wall_mode_tiles_up_to_four_sessions_and_shows_more_strip(tmp_path):
    make_sessions_dir(tmp_path, 6)
    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("w")
        await pilot.pause()

        assert len(app._wall_panes) == 4
        more_strip = app.query_one("#wall-more")
        assert "2" in str(more_strip.content)


@pytest.mark.asyncio
async def test_wall_mode_pane_receives_live_events(tmp_path):
    session_dir = tmp_path / "sess-a"
    write_event(session_dir / "main.jsonl", "sess-a", "SessionStart", 100.0)

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("w")
        await pilot.pause()
        pane = app._wall_panes["sess-a"]
        lines_before = len(pane.lines)

        write_event(session_dir / "main.jsonl", "sess-a", "PreToolUse", 101.0, tool_name="Bash")
        await asyncio.sleep(0.6)
        await pilot.pause()

        assert len(pane.lines) == lines_before + 1

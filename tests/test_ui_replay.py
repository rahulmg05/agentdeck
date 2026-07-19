"""Phase 6 replay tests: speed/pause/seek, and the session browser screen."""

import json
from pathlib import Path

import pytest

from agentdeck.events import parse_line
from agentdeck.ui.app import AgentDeckApp
from agentdeck.ui.widgets.session_browser_screen import SessionBrowserScreen

FIXTURES = Path(__file__).parent / "fixtures"


def load_events(fixture_name: str) -> list:
    path = FIXTURES / fixture_name / "main.jsonl"
    return [parse_line(line, path) for line in path.read_text().splitlines() if line.strip()]


def synthetic_events(n: int, gap: float = 0.05) -> list:
    events = []
    for i in range(n):
        line = json.dumps(
            {
                "ad_schema": 1,
                "ad_ts": 1000.0 + i * gap,
                "ad_seq": 0,
                "ad_host_pid": 1,
                "event": {
                    "session_id": "sess-replay",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_use_id": f"t{i}",
                },
            }
        )
        events.append(parse_line(line, Path("sess-replay/main.jsonl")))
    return events


@pytest.mark.asyncio
async def test_replay_plays_all_events_to_completion():
    import asyncio

    events = synthetic_events(5, gap=0.02)
    app = AgentDeckApp(replay_events=events)
    async with app.run_test():
        assert app.is_replay is True
        app.replay_speed_index = 3  # max speed — tiny gaps, finishes almost immediately

        for _ in range(50):
            if app.replay_finished:
                break
            await asyncio.sleep(0.05)

        assert app.replay_finished is True
        assert app.replay_position == len(events)
        assert app.event_count == len(events)


@pytest.mark.asyncio
async def test_replay_pause_stops_progress():
    events = synthetic_events(20, gap=0.05)
    app = AgentDeckApp(replay_events=events)
    async with app.run_test() as pilot:
        await pilot.press("space")
        assert app.replay_paused is True

        position_after_pause = app.replay_position
        import asyncio

        await asyncio.sleep(0.3)
        assert app.replay_position == position_after_pause

        await pilot.press("space")
        assert app.replay_paused is False


@pytest.mark.asyncio
async def test_replay_seek_forward_and_back_resets_state_consistently():
    events = synthetic_events(20, gap=0.001)
    app = AgentDeckApp(replay_events=events)
    async with app.run_test() as pilot:
        await pilot.press("space")  # pause immediately so seeking is deterministic
        import asyncio

        await asyncio.sleep(0.1)

        app._replay_jump_to(10)
        assert app.replay_position == 10
        assert app.event_count == 10

        await pilot.press("right")
        assert app.replay_position == 12  # chunk = max(1, 20//10) = 2

        await pilot.press("left")
        await pilot.press("left")
        assert app.replay_position == 8


@pytest.mark.asyncio
async def test_replay_speed_keys_cycle_through_speeds():
    events = synthetic_events(3)
    app = AgentDeckApp(replay_events=events)
    async with app.run_test() as pilot:
        await pilot.press("space")  # pause so we can inspect state calmly
        assert app.replay_speed_index == 0

        await pilot.press("]")
        assert app.replay_speed_index == 1
        await pilot.press("]")
        await pilot.press("]")
        await pilot.press("]")  # already at max, should clamp
        assert app.replay_speed_index == 3

        await pilot.press("[")
        assert app.replay_speed_index == 2


@pytest.mark.asyncio
async def test_replay_real_fixture_session_reaches_same_final_state_as_live_load():
    events = load_events("multi_tool_session")
    app = AgentDeckApp(replay_events=events)
    async with app.run_test():
        app._replay_jump_to(len(events))  # instant fast-forward to the end
        info = app.registry.get("908bae29-5913-4bde-8177-21f252c520a3")
        assert info is not None
        assert info.tool_count == 2


@pytest.mark.asyncio
async def test_session_browser_dismiss_with_selection_starts_replay(tmp_path):
    for name, ts in [("sess-a", 100.0)]:
        d = tmp_path / name
        d.mkdir()
        (d / "main.jsonl").write_text(
            f'{{"ad_schema":1,"ad_ts":{ts},"ad_seq":0,"ad_host_pid":1,'
            f'"event":{{"session_id":"{name}","hook_event_name":"SessionStart"}}}}\n'
        )

    app = AgentDeckApp(sessions_dir=tmp_path, show_browser=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SessionBrowserScreen)

        await pilot.press("enter")
        await pilot.pause()

        assert app.is_replay is True
        assert len(app.replay_events) == 1

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agentdeck.ui.app import AgentDeckApp


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


@pytest.mark.asyncio
async def test_notification_event_triggers_send_when_enabled(tmp_path):
    write_event(tmp_path / "sess-1" / "main.jsonl", "sess-1", "SessionStart", 100.0)

    with patch("agentdeck.ui.app.notifications_enabled", return_value=True):
        app = AgentDeckApp(sessions_dir=tmp_path)
        async with app.run_test():
            assert app.notify_enabled is True
            with patch("agentdeck.ui.app.send_notification") as mock_send:
                app._handle_event(
                    _make_event(tmp_path, "sess-1", "Notification", 101.0, message="hi there")
                )
                mock_send.assert_called_once()
                assert "hi there" in mock_send.call_args.args[1]


@pytest.mark.asyncio
async def test_notifications_off_by_default_no_send_attempted(tmp_path):
    write_event(tmp_path / "sess-1" / "main.jsonl", "sess-1", "SessionStart", 100.0)

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test():
        assert app.notify_enabled is False
        with patch("agentdeck.ui.app.send_notification") as mock_send:
            app._handle_event(
                _make_event(tmp_path, "sess-1", "Notification", 101.0, message="hi")
            )
            mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_long_tool_call_triggers_notification(tmp_path):
    write_event(tmp_path / "sess-1" / "main.jsonl", "sess-1", "SessionStart", 100.0)

    with patch("agentdeck.ui.app.notifications_enabled", return_value=True):
        app = AgentDeckApp(sessions_dir=tmp_path)
        async with app.run_test():
            with patch("agentdeck.ui.app.send_notification") as mock_send:
                app._handle_event(
                    _make_event(
                        tmp_path, "sess-1", "PostToolUse", 101.0,
                        tool_name="Bash", tool_use_id="t1", duration_ms=45_000,
                    )
                )
                mock_send.assert_called_once()
                assert "45s" in mock_send.call_args.args[1]


@pytest.mark.asyncio
async def test_short_tool_call_does_not_trigger_notification(tmp_path):
    write_event(tmp_path / "sess-1" / "main.jsonl", "sess-1", "SessionStart", 100.0)

    with patch("agentdeck.ui.app.notifications_enabled", return_value=True):
        app = AgentDeckApp(sessions_dir=tmp_path)
        async with app.run_test():
            with patch("agentdeck.ui.app.send_notification") as mock_send:
                app._handle_event(
                    _make_event(
                        tmp_path, "sess-1", "PostToolUse", 101.0,
                        tool_name="Bash", tool_use_id="t1", duration_ms=500,
                    )
                )
                mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_replay_mode_never_sends_notifications():
    from agentdeck.events import parse_line

    line = json.dumps(
        {
            "ad_schema": 1, "ad_ts": 100.0, "ad_seq": 0, "ad_host_pid": 1,
            "event": {"session_id": "s", "hook_event_name": "Notification", "message": "hi"},
        }
    )
    event = parse_line(line, Path("s/main.jsonl"))

    with patch("agentdeck.ui.app.notifications_enabled", return_value=True):
        app = AgentDeckApp(replay_events=[event])
        async with app.run_test():
            with patch("agentdeck.ui.app.send_notification") as mock_send:
                app._handle_event(event)
                mock_send.assert_not_called()


def _make_event(sessions_dir, session_id, hook_event_name, ts, **extra):
    from agentdeck.events import parse_line

    line = json.dumps(
        {
            "ad_schema": 1,
            "ad_ts": ts,
            "ad_seq": 0,
            "ad_host_pid": 1,
            "event": {"session_id": session_id, "hook_event_name": hook_event_name, **extra},
        }
    )
    return parse_line(line, sessions_dir / session_id / "main.jsonl")

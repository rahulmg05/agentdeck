import json
import shutil
from pathlib import Path

import pytest

from agentdeck.ui.app import AgentDeckApp
from agentdeck.ui.widgets.chat_transcript_screen import ChatTranscriptScreen

SAMPLE_TRANSCRIPT = Path(__file__).parent / "transcript_fixtures" / "sample_transcript.jsonl"


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
async def test_chat_transcript_key_opens_screen_with_user_prompt(tmp_path):
    write_event(tmp_path / "sess-1" / "main.jsonl", "sess-1", "SessionStart", 100.0)
    write_event(tmp_path / "sess-1" / "main.jsonl", "sess-1", "UserPromptSubmit", 101.0, prompt="hello there")

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("t")
        await pilot.pause()

        assert isinstance(app.screen, ChatTranscriptScreen)
        assert app.screen.messages[0].text == "hello there"

        await pilot.press("escape")
        assert not isinstance(app.screen, ChatTranscriptScreen)


@pytest.mark.asyncio
async def test_chat_transcript_includes_assistant_text_from_real_transcript(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    shutil.copy(SAMPLE_TRANSCRIPT, transcript)

    write_event(
        tmp_path / "sess-1" / "main.jsonl", "sess-1", "SessionStart", 100.0,
        transcript_path=str(transcript),
    )
    write_event(
        tmp_path / "sess-1" / "main.jsonl", "sess-1", "UserPromptSubmit", 101.0,
        prompt="what's up", transcript_path=str(transcript),
    )

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("t")
        await pilot.pause()

        texts = [m.text for m in app.screen.messages]
        assert "what's up" in texts
        assert "hi" in texts  # from the fixture's assistant text block


@pytest.mark.asyncio
async def test_chat_transcript_key_with_no_selected_session_does_nothing(tmp_path):
    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("t")
        await pilot.pause()
        assert not isinstance(app.screen, ChatTranscriptScreen)

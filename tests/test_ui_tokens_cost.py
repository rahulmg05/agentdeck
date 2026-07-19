"""Phase 5 tests: transcript polling wired into the live app, cost shown in
the stats bar, and the per-session stats panel (tokens/cost)."""

import json
from pathlib import Path

import pytest

from agentdeck.ui.app import AgentDeckApp
from agentdeck.ui.widgets.session_stats_panel import SessionStatsPanel


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


def write_transcript_usage(path: Path, model: str, input_tokens: int, output_tokens: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "type": "assistant",
        "sessionId": "sess-1",
        "timestamp": "2026-07-18T20:00:00.000Z",
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    }
    with open(path, "a") as f:
        f.write(json.dumps(line) + "\n")


@pytest.mark.asyncio
async def test_session_stats_panel_shows_zero_before_any_transcript_data(tmp_path):
    write_event(tmp_path / "sess-1" / "main.jsonl", "sess-1", "SessionStart", 100.0)

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test():
        panel = app.query_one("#session-stats-panel", SessionStatsPanel)
        text = str(panel.query_one("#session-stats-text").content)
        assert "tokens: 0" in text
        assert "$0.0000" in text


@pytest.mark.asyncio
async def test_transcript_polling_updates_session_stats_panel(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    write_event(
        tmp_path / "sess-1" / "main.jsonl",
        "sess-1",
        "SessionStart",
        100.0,
        transcript_path=str(transcript),
    )
    write_transcript_usage(transcript, "claude-sonnet-5", 1_000_000, 1_000_000)

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test():
        app._poll_transcripts()

        info = app.registry.get("sess-1")
        assert info.input_tokens == 1_000_000
        assert info.output_tokens == 1_000_000
        assert info.cost_usd > 0

        panel = app.query_one("#session-stats-panel", SessionStatsPanel)
        text = str(panel.query_one("#session-stats-text").content)
        assert "tokens: 2,000,000" in text


@pytest.mark.asyncio
async def test_stats_bar_shows_aggregate_cost_across_sessions(tmp_path):
    t1, t2 = tmp_path / "t1.jsonl", tmp_path / "t2.jsonl"
    write_event(tmp_path / "sess-a" / "main.jsonl", "sess-a", "SessionStart", 100.0, transcript_path=str(t1))
    write_event(tmp_path / "sess-b" / "main.jsonl", "sess-b", "SessionStart", 101.0, transcript_path=str(t2))
    write_transcript_usage(t1, "claude-sonnet-5", 1_000_000, 0)
    write_transcript_usage(t2, "claude-sonnet-5", 1_000_000, 0)

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test():
        app._poll_transcripts()
        stats_text = str(app.query_one("#stats").content)
        assert "est. cost: $6.0000" in stats_text  # 2 * 1M input tokens @ $3/M


@pytest.mark.asyncio
async def test_switching_selected_session_updates_stats_panel(tmp_path):
    t1, t2 = tmp_path / "t1.jsonl", tmp_path / "t2.jsonl"
    write_event(tmp_path / "sess-a" / "main.jsonl", "sess-a", "SessionStart", 100.0, transcript_path=str(t1))
    write_event(tmp_path / "sess-b" / "main.jsonl", "sess-b", "SessionStart", 101.0, transcript_path=str(t2))
    write_transcript_usage(t1, "claude-sonnet-5", 500_000, 0)
    write_transcript_usage(t2, "claude-sonnet-5", 999_000, 0)

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test() as pilot:
        app._poll_transcripts()
        await pilot.press("tab")  # sess-a is most recent by ad_ts order... move to next

        panel = app.query_one("#session-stats-panel", SessionStatsPanel)
        text = str(panel.query_one("#session-stats-text").content)
        selected_info = app.registry.get(app.selected_session_id)
        assert f"{selected_info.input_tokens:,}" in text


@pytest.mark.asyncio
async def test_transcript_reader_reused_not_recreated_each_poll(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    write_event(
        tmp_path / "sess-1" / "main.jsonl", "sess-1", "SessionStart", 100.0,
        transcript_path=str(transcript),
    )
    write_transcript_usage(transcript, "claude-sonnet-5", 100, 50)

    app = AgentDeckApp(sessions_dir=tmp_path)
    async with app.run_test():
        app._poll_transcripts()
        reader_first = app._transcript_readers["sess-1"]
        app._poll_transcripts()
        reader_second = app._transcript_readers["sess-1"]
        assert reader_first is reader_second

        # usage from the first poll must not be double-counted on the second
        info = app.registry.get("sess-1")
        assert info.input_tokens == 100

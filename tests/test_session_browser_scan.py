from pathlib import Path

from blackbox.pricing import DEFAULT_PRICING
from blackbox.reader import load_session_events, scan_sessions

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_session_events_reads_main_and_agent_files():
    events = load_session_events(FIXTURES / "subagent_delegation")
    assert len(events) > 0
    assert any(e.agent_id for e in events)
    assert any(e.agent_id is None for e in events)
    # sorted by bb_ts
    assert all(events[i].bb_ts <= events[i + 1].bb_ts for i in range(len(events) - 1))


def test_load_session_events_empty_dir_returns_empty(tmp_path):
    empty = tmp_path / "sess-empty"
    empty.mkdir()
    assert load_session_events(empty) == []


def test_scan_sessions_summarizes_all_fixture_sessions():
    summaries = scan_sessions(FIXTURES, DEFAULT_PRICING)
    assert len(summaries) == 3
    names = {s.session_id for s in summaries}
    assert names == {"multi_tool_session", "missing_post_on_failed_read", "subagent_delegation"}


def test_scan_sessions_computes_duration_bounds():
    summaries = scan_sessions(FIXTURES, DEFAULT_PRICING)
    for s in summaries:
        assert s.started_at is not None
        assert s.ended_at is not None
        assert s.started_at <= s.ended_at
        assert s.event_count > 0


def test_scan_sessions_missing_dir_returns_empty(tmp_path):
    assert scan_sessions(tmp_path / "does-not-exist", DEFAULT_PRICING) == []


def test_scan_sessions_ignores_empty_session_directory(tmp_path):
    (tmp_path / "sess-empty").mkdir()
    real_session = tmp_path / "sess-real"
    real_session.mkdir()
    (real_session / "main.jsonl").write_text(
        '{"bb_schema":1,"bb_ts":100.0,"bb_seq":0,"bb_host_pid":1,'
        '"event":{"session_id":"sess-real","hook_event_name":"SessionStart"}}\n'
    )

    summaries = scan_sessions(tmp_path, DEFAULT_PRICING)
    assert len(summaries) == 1
    assert summaries[0].session_id == "sess-real"


def test_scan_sessions_sorted_most_recent_first(tmp_path):
    for name, ts in [("older", 100.0), ("newer", 200.0)]:
        d = tmp_path / name
        d.mkdir()
        (d / "main.jsonl").write_text(
            f'{{"bb_schema":1,"bb_ts":{ts},"bb_seq":0,"bb_host_pid":1,'
            f'"event":{{"session_id":"{name}","hook_event_name":"SessionStart"}}}}\n'
        )

    summaries = scan_sessions(tmp_path, DEFAULT_PRICING)
    assert [s.session_id for s in summaries] == ["newer", "older"]

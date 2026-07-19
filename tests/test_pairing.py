import json
from pathlib import Path

from agentdeck.events import parse_line
from agentdeck.pairing import PairTracker, ToolCallStatus, TurnGrouper

FIXTURES = Path(__file__).parent / "fixtures"


def load_events(fixture_name: str, filename: str = "main.jsonl"):
    path = FIXTURES / fixture_name / filename
    return [parse_line(line, path) for line in path.read_text().splitlines() if line.strip()]


def make_event(session_id, hook_event_name, ad_ts, **raw_extra):
    line = json.dumps(
        {
            "ad_schema": 1,
            "ad_ts": ad_ts,
            "ad_seq": 0,
            "ad_host_pid": 1,
            "event": {"session_id": session_id, "hook_event_name": hook_event_name, **raw_extra},
        }
    )
    return parse_line(line, Path("sess-1/main.jsonl"))


def test_pre_then_post_resolves_done_with_duration_from_event():
    tracker = PairTracker()
    pre = make_event("s1", "PreToolUse", 100.0, tool_name="Bash", tool_use_id="t1")
    post = make_event("s1", "PostToolUse", 100.5, tool_name="Bash", tool_use_id="t1", duration_ms=500)

    tracker.observe(pre)
    call = tracker.observe(post)

    assert call.status == ToolCallStatus.DONE
    assert call.duration_ms == 500
    assert tracker.open_calls() == []


def test_falls_back_to_ad_ts_delta_when_duration_ms_missing():
    tracker = PairTracker()
    tracker.observe(make_event("s1", "PreToolUse", 100.0, tool_name="Bash", tool_use_id="t1"))
    call = tracker.observe(make_event("s1", "PostToolUse", 100.25, tool_name="Bash", tool_use_id="t1"))

    assert call.duration_ms == 250.0


def test_inverted_timestamps_clamp_to_zero_not_negative():
    # The exact scenario discussed at length: under scheduling load, a Pre
    # courier can be measured *after* its own Post courier.
    tracker = PairTracker()
    tracker.observe(make_event("s1", "PreToolUse", 100.5, tool_name="Bash", tool_use_id="t1"))
    call = tracker.observe(make_event("s1", "PostToolUse", 100.0, tool_name="Bash", tool_use_id="t1"))

    assert call.duration_ms == 0.0


def test_post_tool_use_failure_marks_failed():
    tracker = PairTracker()
    tracker.observe(make_event("s1", "PreToolUse", 100.0, tool_name="Bash", tool_use_id="t1"))
    call = tracker.observe(
        make_event("s1", "PostToolUseFailure", 100.1, tool_name="Bash", tool_use_id="t1")
    )
    assert call.status == ToolCallStatus.FAILED


def test_parallel_calls_resolved_independently_by_tool_use_id():
    tracker = PairTracker()
    tracker.observe(make_event("s1", "PreToolUse", 100.0, tool_name="Read", tool_use_id="A"))
    tracker.observe(make_event("s1", "PreToolUse", 100.1, tool_name="Bash", tool_use_id="B"))
    # B finishes first even though A started first — must not get confused
    # by arrival order (this is exactly the FIFO-mismatch risk flagged in
    # the design doc).
    call_b = tracker.observe(
        make_event("s1", "PostToolUse", 100.2, tool_name="Bash", tool_use_id="B", duration_ms=100)
    )
    call_a = tracker.observe(
        make_event("s1", "PostToolUse", 100.9, tool_name="Read", tool_use_id="A", duration_ms=800)
    )

    assert call_a.tool_use_id == "A"
    assert call_a.duration_ms == 800
    assert call_b.tool_use_id == "B"
    assert call_b.duration_ms == 100


def test_real_fixture_missing_post_resolves_via_batch():
    """The real, documented gap: a permission-denied Read never gets an
    individual PostToolUse, only shows up inside PostToolBatch."""
    tracker = PairTracker()
    for event in load_events("missing_post_on_failed_read"):
        tracker.observe(event)

    assert tracker.open_calls() == []
    assert len(tracker.resolved) == 1
    call = tracker.resolved[0]
    assert call.tool_name == "Read"
    assert call.status == ToolCallStatus.DONE
    assert "permission" in str(call.tool_response).lower()


def test_real_fixture_multi_tool_session_all_resolve():
    tracker = PairTracker()
    for event in load_events("multi_tool_session"):
        tracker.observe(event)

    assert tracker.open_calls() == []
    assert len(tracker.resolved) == 2
    names = {c.tool_name for c in tracker.resolved}
    assert names == {"Read", "Bash"}
    for call in tracker.resolved:
        assert call.duration_ms is not None


def test_real_fixture_subagent_session_all_resolve():
    tracker = PairTracker()
    for event in load_events("subagent_delegation", "agent-a0ba1fb5d83100135.jsonl"):
        tracker.observe(event)

    assert tracker.open_calls() == []
    assert len(tracker.resolved) == 2


def test_turn_grouper_groups_events_under_prompt():
    grouper = TurnGrouper()
    grouper.observe(make_event("s1", "UserPromptSubmit", 100.0, prompt="do a thing"))
    grouper.observe(make_event("s1", "PreToolUse", 100.1, tool_name="Bash", tool_use_id="t1"))
    grouper.observe(make_event("s1", "PostToolUse", 100.2, tool_name="Bash", tool_use_id="t1"))
    grouper.observe(make_event("s1", "UserPromptSubmit", 101.0, prompt="do another thing"))
    grouper.observe(make_event("s1", "PreToolUse", 101.1, tool_name="Read", tool_use_id="t2"))

    assert len(grouper.turns) == 2
    assert len(grouper.turns[0].events) == 3
    assert len(grouper.turns[1].events) == 2
    assert grouper.turns[0].prompt_event.raw["prompt"] == "do a thing"


def test_turn_grouper_events_before_any_prompt_get_ungrouped_turn():
    grouper = TurnGrouper()
    grouper.observe(make_event("s1", "SessionStart", 100.0))
    assert len(grouper.turns) == 1
    assert grouper.turns[0].prompt_event is None

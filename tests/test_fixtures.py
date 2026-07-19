"""Regression tests against real captured fixtures (docs/payloads.md). These
guard the assumptions later phases (pairing, dispatch) will be built on."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load(fixture_name: str, filename: str = "main.jsonl") -> list[dict]:
    path = FIXTURES / fixture_name / filename
    return [json.loads(line)["event"] for line in path.read_text().splitlines()]


def test_all_fixture_lines_parse():
    for f in FIXTURES.rglob("*.jsonl"):
        for line in f.read_text().splitlines():
            json.loads(line)


def test_pre_and_post_tool_use_share_tool_use_id():
    events = load("multi_tool_session")
    pre_ids = {e["tool_use_id"] for e in events if e["hook_event_name"] == "PreToolUse"}
    post_ids = {e["tool_use_id"] for e in events if e["hook_event_name"] == "PostToolUse"}
    assert pre_ids == post_ids
    assert len(pre_ids) == 2


def test_post_tool_use_carries_duration_ms():
    events = load("multi_tool_session")
    posts = [e for e in events if e["hook_event_name"] == "PostToolUse"]
    assert all("duration_ms" in e for e in posts)


def test_denied_tool_call_has_no_individual_post_event():
    """Documents a real gap: a permission-denied call gets PreToolUse and shows
    up inside PostToolBatch.tool_calls, but never gets its own PostToolUse,
    PostToolUseFailure, or PermissionDenied event."""
    events = load("missing_post_on_failed_read")
    event_names = [e["hook_event_name"] for e in events]
    assert "PreToolUse" in event_names
    assert "PostToolUse" not in event_names
    assert "PostToolUseFailure" not in event_names
    assert "PermissionDenied" not in event_names

    denied_tool_use_id = next(e for e in events if e["hook_event_name"] == "PreToolUse")[
        "tool_use_id"
    ]
    batch = next(e for e in events if e["hook_event_name"] == "PostToolBatch")
    batch_ids = {c["tool_use_id"] for c in batch["tool_calls"]}
    assert denied_tool_use_id in batch_ids


def test_subagent_events_carry_agent_id_and_are_isolated_from_main():
    agent_events = load("subagent_delegation", "agent-a0ba1fb5d83100135.jsonl")
    assert all(e.get("agent_id") == "a0ba1fb5d83100135" for e in agent_events)
    assert {"SubagentStart", "SubagentStop"} <= {e["hook_event_name"] for e in agent_events}

    main_events = load("subagent_delegation")
    assert all(e.get("agent_id") is None for e in main_events)
    assert "SubagentStart" not in {e["hook_event_name"] for e in main_events}


def test_parent_sees_subagent_launch_as_agent_tool_call():
    main_events = load("subagent_delegation")
    tool_names = {e.get("tool_name") for e in main_events if e["hook_event_name"] == "PreToolUse"}
    assert "Agent" in tool_names

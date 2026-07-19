import json
from pathlib import Path

from agentdeck.events import parse_line
from agentdeck.ui.theme import icon_for


def make_event(hook_event_name: str, **extra) -> object:
    line = json.dumps(
        {
            "ad_schema": 1,
            "ad_ts": 100.0,
            "ad_seq": 0,
            "ad_host_pid": 1,
            "event": {"session_id": "s1", "hook_event_name": hook_event_name, **extra},
        }
    )
    return parse_line(line, Path("s1/main.jsonl"))


def test_icon_for_known_tools():
    for tool, expected in [
        ("Glob", "🔍"),
        ("Grep", "🔎"),
        ("WebFetch", "🌐"),
        ("WebSearch", "🔎"),
        ("NotebookEdit", "📓"),
        ("Agent", "🤖"),
        ("TodoWrite", "📋"),
        ("BashOutput", "📤"),
        ("KillShell", "⛔"),
    ]:
        event = make_event("PreToolUse", tool_name=tool)
        assert icon_for(event) == expected


def test_icon_for_unknown_tool_falls_back_to_generic_event_icon():
    event = make_event("PreToolUse", tool_name="SomeBrandNewTool")
    assert icon_for(event) == "⚙"


def test_icon_for_unknown_event_falls_back_to_bullet():
    event = make_event("SomeBrandNewEvent")
    assert icon_for(event) == "•"


def test_icon_for_failure_event_is_always_x_regardless_of_tool():
    event = make_event("PostToolUseFailure", tool_name="Glob")
    assert icon_for(event) == "✗"

import json
from pathlib import Path

from blackbox.events import SessionRegistry, parse_line, stable_color


def make_event(session_id: str, cwd: str, hook_event_name: str = "PreToolUse") -> object:
    line = json.dumps(
        {
            "bb_schema": 1,
            "bb_ts": 100.0,
            "bb_seq": 0,
            "bb_host_pid": 1,
            "event": {"session_id": session_id, "cwd": cwd, "hook_event_name": hook_event_name},
        }
    )
    return parse_line(line, Path(f"{session_id}/main.jsonl"))


def test_app_color_derived_from_cwd_basename():
    registry = SessionRegistry()
    registry.observe(make_event("s1", "/Users/me/projects/blackbox"))
    info = registry.get("s1")
    assert info.app_color == stable_color("blackbox")


def test_sessions_in_same_project_share_app_color_but_not_session_color():
    registry = SessionRegistry()
    registry.observe(make_event("s1", "/Users/me/projects/blackbox"))
    registry.observe(make_event("s2", "/Users/me/projects/blackbox"))

    info1 = registry.get("s1")
    info2 = registry.get("s2")
    assert info1.app_color == info2.app_color
    assert info1.color != info2.color  # sha256("s1") != sha256("s2") for our palette


def test_sessions_in_different_projects_get_different_app_colors():
    registry = SessionRegistry()
    registry.observe(make_event("s1", "/Users/me/projects/blackbox"))
    registry.observe(make_event("s2", "/Users/me/projects/other-repo"))

    info1 = registry.get("s1")
    info2 = registry.get("s2")
    assert info1.app_color != info2.app_color


def test_app_color_defaults_before_any_cwd_seen():
    registry = SessionRegistry()
    line = json.dumps(
        {
            "bb_schema": 1, "bb_ts": 100.0, "bb_seq": 0, "bb_host_pid": 1,
            "event": {"session_id": "s1", "hook_event_name": "PreToolUse"},
        }
    )
    registry.observe(parse_line(line, Path("s1/main.jsonl")))
    assert registry.get("s1").app_color == "#ffffff"

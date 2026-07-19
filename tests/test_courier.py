"""Unit tests for courier/emit.py. Runs it as a real subprocess (it must work
standalone, without the blackbox package installed) against an isolated HOME
so tests never touch the developer's real ~/.blackbox.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

COURIER = Path(__file__).resolve().parent.parent / "courier" / "emit.py"


def run_courier(stdin_text: str, home: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(COURIER)],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_valid_event_written(tmp_path):
    event = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-1",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
    }
    result = run_courier(json.dumps(event), tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""

    out_file = tmp_path / ".blackbox" / "sessions" / "sess-1" / "main.jsonl"
    lines = read_lines(out_file)
    assert len(lines) == 1
    assert lines[0]["event"]["tool_name"] == "Bash"
    assert lines[0]["bb_schema"] == 1
    assert "bb_ts" in lines[0]


def test_subagent_routed_to_own_file(tmp_path):
    event = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-1",
        "agent_id": "agent-42",
        "tool_name": "Read",
        "tool_input": {"file_path": "/x"},
    }
    run_courier(json.dumps(event), tmp_path)

    main_file = tmp_path / ".blackbox" / "sessions" / "sess-1" / "main.jsonl"
    agent_file = tmp_path / ".blackbox" / "sessions" / "sess-1" / "agent-agent-42.jsonl"
    assert not main_file.exists()
    assert agent_file.exists()


def test_empty_stdin_does_not_crash(tmp_path):
    result = run_courier("", tmp_path)
    assert result.returncode == 0
    assert result.stdout == ""


def test_garbage_stdin_recorded_not_dropped(tmp_path):
    result = run_courier("not json at all {{{", tmp_path)
    assert result.returncode == 0

    out_file = tmp_path / ".blackbox" / "sessions" / "_unknown" / "main.jsonl"
    lines = read_lines(out_file)
    assert lines[0]["event"]["bb_parse_error"] is True


def test_huge_field_is_truncated(tmp_path):
    event = {
        "hook_event_name": "PostToolUse",
        "session_id": "sess-huge",
        "tool_response": "A" * 40_000,
    }
    run_courier(json.dumps(event), tmp_path)

    out_file = tmp_path / ".blackbox" / "sessions" / "sess-huge" / "main.jsonl"
    lines = read_lines(out_file)
    assert lines[0]["bb_truncated"] is True
    assert len(lines[0]["event"]["tool_response"]) < 40_000
    assert "bb_truncated" in lines[0]["event"]["tool_response"]


def test_redacts_env_style_secret_assignment(tmp_path):
    event = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-secret",
        "tool_input": {"command": "export API_KEY=sk-abc123XYZsecretvalue"},
    }
    run_courier(json.dumps(event), tmp_path)

    out_file = tmp_path / ".blackbox" / "sessions" / "sess-secret" / "main.jsonl"
    lines = read_lines(out_file)
    command = lines[0]["event"]["tool_input"]["command"]
    assert "sk-abc123XYZsecretvalue" not in command
    assert "REDACTED" in command


def test_redacts_authorization_bearer_header(tmp_path):
    event = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-secret2",
        "tool_input": {"command": 'curl -H "Authorization: Bearer sk-supersecrettoken123"'},
    }
    run_courier(json.dumps(event), tmp_path)

    out_file = tmp_path / ".blackbox" / "sessions" / "sess-secret2" / "main.jsonl"
    lines = read_lines(out_file)
    command = lines[0]["event"]["tool_input"]["command"]
    assert "sk-supersecrettoken123" not in command
    assert command.count("REDACTED") == 1  # not double-redacted


def test_multiple_events_append_in_order(tmp_path):
    for i in range(5):
        event = {"hook_event_name": "PreToolUse", "session_id": "sess-multi", "seq": i}
        run_courier(json.dumps(event), tmp_path)

    out_file = tmp_path / ".blackbox" / "sessions" / "sess-multi" / "main.jsonl"
    lines = read_lines(out_file)
    assert [line["event"]["seq"] for line in lines] == [0, 1, 2, 3, 4]


def test_session_id_sanitized_for_filesystem(tmp_path):
    event = {
        "hook_event_name": "PreToolUse",
        "session_id": "../../etc/passwd",
    }
    run_courier(json.dumps(event), tmp_path)

    sessions_dir = tmp_path / ".blackbox" / "sessions"
    # must not have escaped the sessions directory
    for f in sessions_dir.rglob("*.jsonl"):
        assert sessions_dir in f.resolve().parents

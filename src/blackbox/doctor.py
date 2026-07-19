"""blackbox doctor — checks that recording is actually working."""

import json
import subprocess
import sys
import time
from pathlib import Path

from blackbox.installer import EVENTS, SETTINGS_PATH, _courier_path

BLACKBOX_DIR = Path.home() / ".blackbox"
SESSIONS_DIR = BLACKBOX_DIR / "sessions"


def _check_registration() -> bool:
    if not SETTINGS_PATH.exists():
        print(f"[FAIL] {SETTINGS_PATH} does not exist — run `blackbox install`")
        return False

    try:
        settings = json.loads(SETTINGS_PATH.read_text())
    except json.JSONDecodeError as exc:
        print(f"[FAIL] {SETTINGS_PATH} is invalid JSON: {exc}")
        return False

    courier_path_str = str(_courier_path())
    hooks = settings.get("hooks", {})
    missing = []
    for event in EVENTS:
        entries = hooks.get(event, [])
        found = any(
            h.get("type") == "command" and courier_path_str in h.get("command", "")
            for entry in entries
            for h in entry.get("hooks", [])
        )
        if not found:
            missing.append(event)

    if missing:
        print(f"[FAIL] courier not registered for {len(missing)} event(s): {', '.join(missing)}")
        return False

    print(f"[PASS] courier registered for all {len(EVENTS)} events")
    return True


def _check_courier_runnable() -> bool:
    courier_path = _courier_path()
    if not courier_path.exists():
        print(f"[FAIL] courier script not found at {courier_path}")
        return False

    sample_event = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "bb-doctor-selftest",
            "tool_name": "Bash",
            "tool_input": {"command": "echo doctor"},
        }
    )
    try:
        result = subprocess.run(
            [sys.executable, str(courier_path)],
            input=sample_event,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        print(f"[FAIL] courier failed to run: {exc}")
        return False

    if result.returncode != 0:
        print(f"[FAIL] courier exited {result.returncode} (should always exit 0)")
        return False
    if result.stdout:
        print(f"[FAIL] courier wrote to stdout (should be silent): {result.stdout!r}")
        return False

    selftest_file = SESSIONS_DIR / "bb-doctor-selftest" / "main.jsonl"
    if not selftest_file.exists():
        print("[FAIL] courier ran but did not write the expected self-test event")
        return False

    selftest_file.unlink()
    try:
        selftest_file.parent.rmdir()
    except OSError:
        pass

    print("[PASS] courier runs cleanly and writes events")
    return True


def _check_log_writable() -> bool:
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        probe = SESSIONS_DIR / ".bb-doctor-probe"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        print(f"[FAIL] {SESSIONS_DIR} is not writable: {exc}")
        return False

    print(f"[PASS] {SESSIONS_DIR} is writable")
    return True


def _check_last_event_age() -> None:
    if not SESSIONS_DIR.exists():
        print("[WARN] no sessions recorded yet")
        return

    newest_mtime = None
    for f in SESSIONS_DIR.rglob("*.jsonl"):
        mtime = f.stat().st_mtime
        if newest_mtime is None or mtime > newest_mtime:
            newest_mtime = mtime

    if newest_mtime is None:
        print("[WARN] no sessions recorded yet")
        return

    age = time.time() - newest_mtime
    if age < 3600:
        print(f"[PASS] most recent event was {age:.0f}s ago")
    else:
        print(f"[WARN] most recent event was {age / 3600:.1f}h ago")


def run_doctor() -> int:
    checks = [_check_registration(), _check_courier_runnable(), _check_log_writable()]
    _check_last_event_age()
    return 0 if all(checks) else 1

#!/usr/bin/env python3
"""Blackbox courier. Reads one Claude Code hook event on stdin, appends one
enriched JSON line to ~/.blackbox/sessions/<session_id>/{main,agent-<id>}.jsonl,
and exits 0 unconditionally.

Stdlib only (principle 6, design doc section 5) — must not import anything
from the `blackbox` console package or any third-party library, since it has
to run standalone wherever Claude Code invokes it, independent of whether the
console is installed.

Must never fail loudly (principle 1): every code path here either succeeds
silently or drops silently. Nothing is ever written to stdout, and the
process always exits 0.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import fcntl  # POSIX only; Windows support is deferred (design doc section 7)
except ImportError:
    fcntl = None

SCHEMA_VERSION = 1
BLACKBOX_DIR = Path.home() / ".blackbox"
SESSIONS_DIR = BLACKBOX_DIR / "sessions"
FALLBACK_ERROR_FILE = BLACKBOX_DIR / "errors.jsonl"

# Each session/agent file rotates independently once it crosses this size
# (design doc section 6).
ROTATE_THRESHOLD_BYTES = 50 * 1024 * 1024

# Any single string field larger than this gets truncated (design doc 3.1: the
# file-per-actor layout narrows collisions enough that this can be well above
# the original ~2KB shared-file figure; revisit against real payload sizes).
TRUNCATE_LIMIT_BYTES = 16 * 1024

REDACTED = "***REDACTED***"

# Principle 5: strip obvious secrets from tool_input/tool_response before the
# line hits disk. Best-effort, not a security guarantee — documented limits.
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Za-z0-9_]*"
    r"(?:SECRET|TOKEN|API[-_]?KEY|PASSWORD|PASSWD|PWD|CREDENTIAL|ACCESS[-_]?KEY)"
    r"[A-Za-z0-9_]*)"
    r"(\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|\S+)"
)
# Handles "Authorization: [Bearer ]<token>" as one unit so a later bare-Bearer
# pass doesn't also match the same token and leave a doubled REDACTED marker.
_AUTH_HEADER_RE = re.compile(r"(?i)\b(Authorization)(\s*:\s*)((?:Bearer\s+)?)\S+")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+\S+")


def _redact_string(value: str) -> str:
    value = _SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", value)
    value = _AUTH_HEADER_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}", value
    )
    value = _BEARER_RE.sub(f"Bearer {REDACTED}", value)
    return value


def _redact_tree(node):
    if isinstance(node, str):
        return _redact_string(node)
    if isinstance(node, dict):
        return {k: _redact_tree(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_redact_tree(v) for v in node]
    return node


def _truncate_tree(node, state):
    if isinstance(node, str):
        encoded = node.encode("utf-8", errors="surrogatepass")
        if len(encoded) > TRUNCATE_LIMIT_BYTES:
            state["truncated"] = True
            head = encoded[:TRUNCATE_LIMIT_BYTES].decode("utf-8", errors="ignore")
            return f"{head}...<bb_truncated original {len(encoded)} bytes>"
        return node
    if isinstance(node, dict):
        return {k: _truncate_tree(v, state) for k, v in node.items()}
    if isinstance(node, list):
        return [_truncate_tree(v, state) for v in node]
    return node


def _redact_and_truncate(event: dict) -> tuple[dict, bool]:
    if "tool_input" in event:
        event["tool_input"] = _redact_tree(event["tool_input"])
    if "tool_response" in event:
        event["tool_response"] = _redact_tree(event["tool_response"])

    state = {"truncated": False}
    event = _truncate_tree(event, state)
    return event, state["truncated"]


def _sanitize_id(value, fallback: str) -> str:
    if not isinstance(value, str) or not value:
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value)[:128]
    return cleaned or fallback


def _determine_path(event: dict) -> Path:
    session_id = _sanitize_id(event.get("session_id"), fallback="_unknown")
    session_dir = SESSIONS_DIR / session_id
    agent_id = event.get("agent_id")
    if agent_id:
        filename = f"agent-{_sanitize_id(agent_id, fallback='unknown')}.jsonl"
    else:
        filename = "main.jsonl"
    return session_dir / filename


def _build_envelope(event: dict, truncated: bool) -> dict:
    envelope = {
        "bb_schema": SCHEMA_VERSION,
        "bb_ts": time.time(),
        "bb_seq": 0,
        "bb_host_pid": os.getpid(),
    }
    if truncated:
        envelope["bb_truncated"] = True
    envelope["event"] = event
    return envelope


def _rotate_if_needed(path: Path) -> None:
    """Best-effort rotation: move an oversized file to archive/ before the next
    append. Guarded by an flock so concurrent couriers for the same actor
    don't race to rotate at once (see design doc section 3.1 on same-actor
    concurrency)."""
    try:
        if not path.exists() or path.stat().st_size <= ROTATE_THRESHOLD_BYTES:
            return
    except OSError:
        return

    lock_path = path.parent / ".rotate.lock"
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return

    try:
        if fcntl is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            if not path.exists() or path.stat().st_size <= ROTATE_THRESHOLD_BYTES:
                return
            archive_dir = path.parent / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            n = 0
            while True:
                candidate = archive_dir / f"{path.stem}-{n}.jsonl"
                if not candidate.exists():
                    break
                n += 1
            os.rename(str(path), str(candidate))
        finally:
            if fcntl is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def _atomic_append(path: Path, line: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_APPEND | os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def _read_event() -> dict:
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {"bb_parse_error": True, "bb_raw_prefix": raw[:200]}
    return parsed if isinstance(parsed, dict) else {"bb_parse_error": True}


def main() -> None:
    try:
        event = _read_event()
        event, truncated = _redact_and_truncate(event)
        envelope = _build_envelope(event, truncated)
        line = (json.dumps(envelope, separators=(",", ":")) + "\n").encode("utf-8")
        path = _determine_path(event)
        _rotate_if_needed(path)
        _atomic_append(path, line)
    except Exception as exc:
        try:
            err_line = (
                json.dumps(
                    {
                        "bb_schema": SCHEMA_VERSION,
                        "bb_ts": time.time(),
                        "bb_host_pid": os.getpid(),
                        "bb_error": str(exc)[:200],
                    },
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            _atomic_append(FALLBACK_ERROR_FILE, err_line)
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()

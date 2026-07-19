import asyncio
import json
from pathlib import Path

import pytest

from agentdeck.reader import Reader


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


def test_load_history_reads_all_events_sorted_by_ts(tmp_path):
    write_event(tmp_path / "sess-a" / "main.jsonl", "sess-a", "PreToolUse", 102.0, tool_use_id="t2")
    write_event(tmp_path / "sess-a" / "main.jsonl", "sess-a", "PreToolUse", 100.0, tool_use_id="t0")
    write_event(tmp_path / "sess-b" / "main.jsonl", "sess-b", "PreToolUse", 101.0, tool_use_id="t1")

    reader = Reader(tmp_path)
    history = reader.load_history()

    assert [e.raw["tool_use_id"] for e in history] == ["t0", "t1", "t2"]


def test_load_history_skips_unparseable_lines_and_counts_them(tmp_path):
    path = tmp_path / "sess-a" / "main.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('not valid json\n{"ad_schema":1,"ad_ts":100.0,"event":{"session_id":"sess-a"}}\n')

    reader = Reader(tmp_path)
    history = reader.load_history()

    assert len(history) == 1
    assert reader.dropped_lines == 1


@pytest.mark.asyncio
async def test_watch_only_yields_new_lines_not_history_already_read(tmp_path):
    path = tmp_path / "sess-a" / "main.jsonl"
    write_event(path, "sess-a", "PreToolUse", 100.0, tool_use_id="old")

    reader = Reader(tmp_path)
    assert len(reader.load_history()) == 1

    seen = []

    async def consume():
        async for event in reader.watch():
            seen.append(event.raw["tool_use_id"])
            if len(seen) >= 1:
                return

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0.2)
    write_event(path, "sess-a", "PreToolUse", 101.0, tool_use_id="new")
    await asyncio.wait_for(task, timeout=5)

    assert seen == ["new"]  # not ["old", "new"] — history must not replay


@pytest.mark.asyncio
async def test_watch_does_not_reread_history_via_a_symlinked_sessions_dir(tmp_path):
    """Regression test: watchfiles.awatch() reports OS-resolved paths
    (symlinks followed), while glob()-based discovery returns paths in
    whatever form sessions_dir was given. If Reader used those as dict
    keys without normalizing, every watch()-triggered read for a file
    would silently miss the offset load_history() had already established
    and restart from 0 — replaying the entire file's history into the live
    stream. Reproduced here with a real symlink rather than relying on a
    platform-specific quirk (e.g. macOS's /var -> /private/var) that
    wouldn't reproduce identically in CI.
    """
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    symlink_dir = tmp_path / "via-symlink"
    symlink_dir.symlink_to(real_dir)

    path = symlink_dir / "sess-a" / "main.jsonl"
    for i in range(10):
        write_event(path, "sess-a", "PreToolUse", 100.0 + i, tool_use_id=f"old{i}")

    reader = Reader(symlink_dir)
    assert len(reader.load_history()) == 10

    seen = []

    async def consume():
        async for event in reader.watch():
            seen.append(event.raw["tool_use_id"])
            if len(seen) >= 3:
                return

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0.2)
    for i in range(3):
        write_event(path, "sess-a", "PreToolUse", 200.0 + i, tool_use_id=f"new{i}")
    await asyncio.wait_for(task, timeout=5)

    assert seen == ["new0", "new1", "new2"]
    assert "old0" not in seen

"""Direct (in-process) tests of the rotation logic in courier/emit.py, since
that needs to poke at internals (threshold, lock file) that the subprocess
black-box tests in test_courier.py intentionally don't reach into."""

import importlib.util
from pathlib import Path

COURIER_PATH = Path(__file__).resolve().parent.parent / "courier" / "emit.py"


def load_emit_module():
    spec = importlib.util.spec_from_file_location("ad_emit_under_test", COURIER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rotate_moves_oversized_file_to_archive(tmp_path, monkeypatch):
    emit = load_emit_module()
    monkeypatch.setattr(emit, "ROTATE_THRESHOLD_BYTES", 100)

    session_dir = tmp_path / "sess-1"
    session_dir.mkdir()
    main_file = session_dir / "main.jsonl"
    main_file.write_text("x" * 200)

    emit._rotate_if_needed(main_file)

    assert not main_file.exists()
    archived = list((session_dir / "archive").glob("main-*.jsonl"))
    assert len(archived) == 1
    assert archived[0].read_text() == "x" * 200


def test_rotate_does_nothing_under_threshold(tmp_path, monkeypatch):
    emit = load_emit_module()
    monkeypatch.setattr(emit, "ROTATE_THRESHOLD_BYTES", 100)

    session_dir = tmp_path / "sess-1"
    session_dir.mkdir()
    main_file = session_dir / "main.jsonl"
    main_file.write_text("small")

    emit._rotate_if_needed(main_file)

    assert main_file.exists()
    assert main_file.read_text() == "small"


def test_rotate_picks_next_free_archive_index(tmp_path, monkeypatch):
    emit = load_emit_module()
    monkeypatch.setattr(emit, "ROTATE_THRESHOLD_BYTES", 100)

    session_dir = tmp_path / "sess-1"
    session_dir.mkdir()
    archive_dir = session_dir / "archive"
    archive_dir.mkdir()
    (archive_dir / "main-0.jsonl").write_text("old-0")
    (archive_dir / "main-1.jsonl").write_text("old-1")

    main_file = session_dir / "main.jsonl"
    main_file.write_text("y" * 200)

    emit._rotate_if_needed(main_file)

    assert (archive_dir / "main-2.jsonl").read_text() == "y" * 200
    assert (archive_dir / "main-0.jsonl").read_text() == "old-0"
    assert (archive_dir / "main-1.jsonl").read_text() == "old-1"


def test_rotate_then_append_starts_fresh_file(tmp_path, monkeypatch):
    emit = load_emit_module()
    monkeypatch.setattr(emit, "ROTATE_THRESHOLD_BYTES", 10)

    session_dir = tmp_path / "sess-1"
    session_dir.mkdir()
    main_file = session_dir / "main.jsonl"
    main_file.write_text("x" * 20)

    emit._rotate_if_needed(main_file)
    emit._atomic_append(main_file, b'{"new":true}\n')

    assert main_file.read_text() == '{"new":true}\n'
    assert list((session_dir / "archive").glob("*.jsonl"))

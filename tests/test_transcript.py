import shutil
from pathlib import Path

from agentdeck.transcript import (
    ChatMessage,
    TranscriptReader,
    build_chat_transcript,
    extract_assistant_messages,
)

SAMPLE = Path(__file__).parent / "transcript_fixtures" / "sample_transcript.jsonl"


def test_reads_only_assistant_messages_with_usage(tmp_path):
    dest = tmp_path / "t.jsonl"
    shutil.copy(SAMPLE, dest)

    reader = TranscriptReader(dest)
    usages = reader.read_new_usage()

    assert len(usages) == 2
    assert usages[0].model == "claude-sonnet-5"
    assert usages[0].input_tokens == 100
    assert usages[0].output_tokens == 50
    assert usages[0].cache_creation_input_tokens == 200
    assert usages[1].input_tokens == 300
    assert usages[1].cache_read_input_tokens == 250


def test_second_read_returns_nothing_new(tmp_path):
    dest = tmp_path / "t.jsonl"
    shutil.copy(SAMPLE, dest)

    reader = TranscriptReader(dest)
    reader.read_new_usage()
    assert reader.read_new_usage() == []


def test_incremental_append_only_returns_new_usage(tmp_path):
    dest = tmp_path / "t.jsonl"
    shutil.copy(SAMPLE, dest)

    reader = TranscriptReader(dest)
    first_batch = reader.read_new_usage()
    assert len(first_batch) == 2

    with open(dest, "a") as f:
        f.write(
            '{"type":"assistant","sessionId":"sess-1","timestamp":"2026-07-18T20:01:00.000Z",'
            '"message":{"model":"claude-sonnet-5","usage":{"input_tokens":10,"output_tokens":5,'
            '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
        )

    second_batch = reader.read_new_usage()
    assert len(second_batch) == 1
    assert second_batch[0].input_tokens == 10


def test_missing_file_returns_empty_not_error(tmp_path):
    reader = TranscriptReader(tmp_path / "does-not-exist.jsonl")
    assert reader.read_new_usage() == []


def test_partial_trailing_line_not_consumed_yet(tmp_path):
    """The eventually-consistent lag caveat: a transcript file mid-write can
    have an incomplete final line. Must not parse-fail on it, and must not
    advance the offset past it — retry on the next read once it's complete.
    """
    full_second_line = (
        '{"type":"assistant","sessionId":"s","timestamp":"t2",'
        '"message":{"model":"m","usage":{"input_tokens":2,"output_tokens":2,'
        '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
    )
    split_point = len(full_second_line) // 2

    dest = tmp_path / "t.jsonl"
    dest.write_text(
        '{"type":"assistant","sessionId":"s","timestamp":"t1",'
        '"message":{"model":"m","usage":{"input_tokens":1,"output_tokens":1,'
        '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
        + full_second_line[:split_point]
    )

    reader = TranscriptReader(dest)
    usages = reader.read_new_usage()
    assert len(usages) == 1  # only the complete line

    # Nothing new yet — the partial line still isn't complete.
    assert reader.read_new_usage() == []

    # Now the writer finishes the line.
    with open(dest, "a") as f:
        f.write(full_second_line[split_point:])

    usages = reader.read_new_usage()
    assert len(usages) == 1
    assert usages[0].input_tokens == 2


def test_non_assistant_lines_ignored(tmp_path):
    dest = tmp_path / "t.jsonl"
    dest.write_text('{"type":"user","message":{"role":"user","content":"hi"}}\n')
    reader = TranscriptReader(dest)
    assert reader.read_new_usage() == []


def test_extract_assistant_messages_skips_tool_use_only_entries():
    messages = extract_assistant_messages(SAMPLE)
    assert len(messages) == 1
    assert messages[0].text == "hi"
    assert messages[0].role == "assistant"


def test_extract_assistant_messages_missing_file_returns_empty(tmp_path):
    assert extract_assistant_messages(tmp_path / "nope.jsonl") == []


def test_extract_assistant_messages_joins_multiple_text_blocks(tmp_path):
    dest = tmp_path / "t.jsonl"
    dest.write_text(
        '{"type":"assistant","timestamp":"2026-01-01T00:00:00.000Z",'
        '"message":{"content":[{"type":"text","text":"first"},'
        '{"type":"thinking","thinking":"secret"},'
        '{"type":"text","text":"second"}]}}\n'
    )
    messages = extract_assistant_messages(dest)
    assert len(messages) == 1
    assert messages[0].text == "first\nsecond"
    assert "secret" not in messages[0].text


def test_build_chat_transcript_merges_user_and_assistant_in_order():
    class FakeEvent:
        def __init__(self, prompt, ts):
            self.raw = {"prompt": prompt}
            self.ad_ts = ts

    # assistant message "hi" is at 2026-07-18T20:00:01Z in the fixture
    import datetime

    assistant_ts = datetime.datetime.fromisoformat("2026-07-18T20:00:01.000Z".replace("Z", "+00:00")).timestamp()

    user_events = [
        FakeEvent("first question", assistant_ts - 10),
        FakeEvent("second question", assistant_ts + 10),
    ]

    transcript = build_chat_transcript(user_events, SAMPLE)

    assert [m.role for m in transcript] == ["user", "assistant", "user"]
    assert transcript[0].text == "first question"
    assert transcript[1].text == "hi"
    assert transcript[2].text == "second question"


def test_build_chat_transcript_with_no_transcript_path_still_returns_user_turns():
    class FakeEvent:
        raw = {"prompt": "hello"}
        ad_ts = 100.0

    transcript = build_chat_transcript([FakeEvent()], None)
    assert transcript == [ChatMessage(role="user", text="hello", ts=100.0)]


def test_build_chat_transcript_skips_events_without_prompt_field():
    class FakeEvent:
        raw = {}
        ad_ts = 100.0

    assert build_chat_transcript([FakeEvent()], None) == []

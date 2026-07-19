"""Transcript reader: tail the JSONL at transcript_path per session, extract
per-message token usage and model id (design doc Phase 5).

Eventually consistent (design doc section 4): the transcript file is written
asynchronously by Claude Code and may lag behind the hook event that reports
its path, so reads here are always best-effort — the file might not exist
yet, might be empty, or might have a partially-written trailing line. Only
ever advance past a line once it's confirmed complete (ends in a newline);
retry the rest next time.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Usage:
    model: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    timestamp: str | None = None


def _parse_usage_line(line: str) -> Usage | None:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return None
    message = obj.get("message")
    if not isinstance(message, dict):
        return None
    usage_obj = message.get("usage")
    if not isinstance(usage_obj, dict):
        return None
    return Usage(
        model=message.get("model"),
        input_tokens=usage_obj.get("input_tokens") or 0,
        output_tokens=usage_obj.get("output_tokens") or 0,
        cache_creation_input_tokens=usage_obj.get("cache_creation_input_tokens") or 0,
        cache_read_input_tokens=usage_obj.get("cache_read_input_tokens") or 0,
        timestamp=obj.get("timestamp"),
    )


class TranscriptReader:
    """One instance per transcript file; tracks its own byte offset for
    incremental tailing (same pattern as reader.Reader, applied to a single
    file instead of a directory tree)."""

    def __init__(self, transcript_path: Path) -> None:
        self.transcript_path = Path(transcript_path)
        self._offset = 0

    def read_new_usage(self) -> list[Usage]:
        try:
            size = self.transcript_path.stat().st_size
        except OSError:
            return []

        if size < self._offset:
            self._offset = 0  # file shrank/rotated — restart from scratch
        if size <= self._offset:
            return []

        with open(self.transcript_path, "rb") as f:
            f.seek(self._offset)
            chunk = f.read()

        last_newline = chunk.rfind(b"\n")
        if last_newline == -1:
            return []  # no complete line yet in this chunk — try again later

        complete_chunk = chunk[: last_newline + 1]
        self._offset += len(complete_chunk)

        usages = []
        for raw_line in complete_chunk.decode("utf-8", errors="replace").splitlines():
            if not raw_line.strip():
                continue
            usage = _parse_usage_line(raw_line)
            if usage is not None:
                usages.append(usage)
        return usages


# ---- chat transcript viewer (feature-parity item) --------------------------


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    text: str
    ts: float


def _parse_iso_ts(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def extract_assistant_messages(transcript_path: Path) -> list[ChatMessage]:
    """One-shot read of assistant text content from a transcript file — not
    incremental, this is for the chat viewer opening a session, not live
    tailing. User turns are deliberately NOT extracted from the transcript
    here: a transcript "user"-role entry can be either a real human prompt
    *or* a tool_result being fed back through the API (that's simply how
    the Anthropic API represents tool results), and disambiguating them
    reliably from the transcript alone is not worth it when
    UserPromptSubmit hook events already give us genuine human prompts
    directly — see build_chat_transcript().
    """
    if not transcript_path.exists():
        return []

    messages = []
    for raw_line in transcript_path.read_text(errors="replace").splitlines():
        if not raw_line.strip():
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("type") != "assistant":
            continue
        message = obj.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue

        text = "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
        )
        if text:
            messages.append(ChatMessage(role="assistant", text=text, ts=_parse_iso_ts(obj.get("timestamp"))))
    return messages


def build_chat_transcript(user_prompt_events, transcript_path: Path | None) -> list[ChatMessage]:
    """Merge UserPromptSubmit hook events (user turns) with assistant text
    extracted from the transcript file, sorted chronologically."""
    messages = [
        ChatMessage(role="user", text=str(e.raw.get("prompt", "")), ts=e.ad_ts)
        for e in user_prompt_events
        if e.raw.get("prompt")
    ]
    if transcript_path is not None:
        messages.extend(extract_assistant_messages(Path(transcript_path)))
    messages.sort(key=lambda m: m.ts)
    return messages

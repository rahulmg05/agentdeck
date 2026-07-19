"""Icon/summary rendering for the firehose (design doc Phase 3 visual design)."""

from blackbox.events import FAILURE_EVENTS, Event

EVENT_ICONS = {
    "UserPromptSubmit": "▸",
    "PreToolUse": "⚙",
    "PostToolUse": "⚙",
    "PostToolBatch": "⚙",
    "SessionStart": "●",
    "SessionEnd": "●",
    "Stop": "■",
    "SubagentStart": "◆",
    "SubagentStop": "◆",
    "Notification": "🔔",
    "PermissionRequest": "🔒",
    "PermissionDenied": "🔒",
    "PreCompact": "▤",
    "PostCompact": "▤",
    "ConfigChange": "⚙",
    "CwdChanged": "📁",
}

TOOL_ICONS = {
    "Bash": "$",
    "Edit": "✎",
    "Write": "✎",
    "Read": "▤",
    "Glob": "🔍",
    "Grep": "🔎",
    "WebFetch": "🌐",
    "WebSearch": "🔎",
    "NotebookEdit": "📓",
    "Agent": "🤖",
    "Task": "🤖",
    "TaskCreate": "📋",
    "TaskUpdate": "📋",
    "TodoWrite": "📋",
    "BashOutput": "📤",
    "KillShell": "⛔",
    "ExitPlanMode": "📝",
    "SlashCommand": "⌨",
}


def icon_for(event: Event) -> str:
    if event.hook_event_name in FAILURE_EVENTS:
        return "✗"
    if event.tool_name and event.tool_name in TOOL_ICONS:
        return TOOL_ICONS[event.tool_name]
    return EVENT_ICONS.get(event.hook_event_name, "•")


def _truncate(text: str, limit: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _summarize_tool_input(tool: str, tool_input: dict) -> str:
    if tool == "Bash":
        return _truncate(str(tool_input.get("command", "")), 60)
    if tool in ("Read", "Write", "Edit"):
        return str(tool_input.get("file_path", ""))
    if tool == "Agent":
        return _truncate(str(tool_input.get("description", "")), 60)
    return _truncate(str(tool_input), 60)


def summarize(event: Event) -> str:
    name = event.hook_event_name

    if name == "UserPromptSubmit":
        return _truncate(str(event.raw.get("prompt", "")), 80)

    if name in ("PreToolUse", "PostToolUse") or name in FAILURE_EVENTS:
        tool = event.tool_name or "?"
        detail = _summarize_tool_input(tool, event.raw.get("tool_input", {}) or {})
        duration = event.raw.get("duration_ms")
        suffix = f" ({duration}ms)" if isinstance(duration, (int, float)) else ""
        return f"{tool} {detail}{suffix}"

    if name == "PostToolBatch":
        calls = event.raw.get("tool_calls") or []
        names = ", ".join(c.get("tool_name", "?") for c in calls)
        return f"batch: {names}" if names else "batch"

    if name in ("SubagentStart", "SubagentStop"):
        return str(event.raw.get("agent_type", "") or "")

    if name in ("SessionStart", "SessionEnd"):
        return str(event.raw.get("source", "") or "")

    return ""

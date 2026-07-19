"""Desktop notifications on Notification events / long-task completion
(design doc Phase 7). Optional, config-gated, off by default — and always
best-effort: a missing platform tool or any other failure here must never
crash or block the console.
"""

import platform
import subprocess
import tomllib
from pathlib import Path

CONFIG_PATH = Path.home() / ".blackbox" / "config.toml"


def notifications_enabled(config_path: Path = CONFIG_PATH) -> bool:
    if not config_path.exists():
        return False
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return False
    notifications = data.get("notifications")
    if not isinstance(notifications, dict):
        return False
    return bool(notifications.get("enabled", False))


def _osascript_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def send_notification(title: str, message: str) -> None:
    try:
        system = platform.system()
        if system == "Darwin":
            script = (
                f"display notification {_osascript_string(message)} "
                f"with title {_osascript_string(title)}"
            )
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)
        elif system == "Linux":
            subprocess.run(["notify-send", title, message], capture_output=True, timeout=3)
        # Windows notifications are out of scope (design doc: Windows support deferred).
    except Exception:
        pass

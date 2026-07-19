"""blackbox install / uninstall — merge or remove courier hook entries in
~/.claude/settings.json. Additive JSON merge: never touches hook entries that
aren't ours, always backs up the file first.
"""

import importlib.resources
import json
import shutil
import sys
import time
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# Keep in sync with the event list in the design doc, section 4.
EVENTS = [
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "Stop",
    "StopFailure",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "PermissionRequest",
    "PermissionDenied",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "Notification",
    "ConfigChange",
    "CwdChanged",
]


def _courier_path() -> Path:
    """Prefer the repo-checkout copy (dev workflow: `uv run blackbox
    install` against a source tree) and fall back to the copy bundled
    inside the installed package (pipx/pip install — see the
    force-include in pyproject.toml, since courier/emit.py lives outside
    src/blackbox and wouldn't otherwise ship in the wheel at all)."""
    dev_path = Path(__file__).resolve().parent.parent.parent / "courier" / "emit.py"
    if dev_path.exists():
        return dev_path
    packaged = importlib.resources.files("blackbox") / "courier" / "emit.py"
    return Path(str(packaged))


def _courier_command() -> str:
    return f"{sys.executable} {_courier_path()}"


def _load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"blackbox: {SETTINGS_PATH} contains invalid JSON ({exc}); "
            "aborting rather than risk corrupting it further"
        )


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup_path = path.with_name(f"{path.name}.bb-backup-{int(time.time())}")
    shutil.copy2(path, backup_path)
    return backup_path


def _write_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")


def _find_courier_entry(entries: list, courier_path_str: str):
    """Return the index of the hooks-config entry that runs our courier, if any."""
    for i, entry in enumerate(entries):
        for h in entry.get("hooks", []):
            if h.get("type") == "command" and courier_path_str in h.get("command", ""):
                return i
    return None


def install() -> None:
    settings = _load_settings()
    backup = _backup(SETTINGS_PATH)
    command = _courier_command()
    courier_path_str = str(_courier_path())

    hooks = settings.setdefault("hooks", {})
    added, updated = [], []
    for event in EVENTS:
        entries = hooks.setdefault(event, [])
        idx = _find_courier_entry(entries, courier_path_str)
        new_entry = {
            "matcher": "*",
            "hooks": [{"type": "command", "command": command, "async": True}],
        }
        if idx is None:
            entries.append(new_entry)
            added.append(event)
        elif entries[idx] != new_entry:
            entries[idx] = new_entry
            updated.append(event)

    _write_settings(settings)

    if backup:
        print(f"blackbox: backed up existing settings to {backup}")
    if added:
        print(f"blackbox: registered courier for {len(added)} event(s): {', '.join(added)}")
    if updated:
        print(f"blackbox: updated courier command for {len(updated)} event(s) (interpreter path changed)")
    if not added and not updated:
        print("blackbox: courier already registered for all events (nothing to do)")


def uninstall() -> None:
    if not SETTINGS_PATH.exists():
        print("blackbox: no settings.json found, nothing to uninstall")
        return

    settings = _load_settings()
    backup = _backup(SETTINGS_PATH)
    courier_path_str = str(_courier_path())
    hooks = settings.get("hooks", {})

    removed_from = []
    for event in list(hooks.keys()):
        kept_entries = []
        for entry in hooks[event]:
            remaining_hooks = [
                h
                for h in entry.get("hooks", [])
                if not (h.get("type") == "command" and courier_path_str in h.get("command", ""))
            ]
            if len(remaining_hooks) != len(entry.get("hooks", [])):
                removed_from.append(event)
            if remaining_hooks:
                kept_entries.append({**entry, "hooks": remaining_hooks})
        if kept_entries:
            hooks[event] = kept_entries
        else:
            del hooks[event]

    if not hooks:
        settings.pop("hooks", None)

    _write_settings(settings)
    if backup:
        print(f"blackbox: backed up settings to {backup}")
    if removed_from:
        print(f"blackbox: removed courier registration from {len(removed_from)} event(s)")
    else:
        print("blackbox: courier was not registered, nothing to remove")

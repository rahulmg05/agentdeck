import json
from pathlib import Path

from blackbox import installer


def _settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(installer, "SETTINGS_PATH", path)
    return path


def test_courier_path_falls_back_to_packaged_copy_when_no_dev_checkout(monkeypatch, tmp_path):
    """Regression test: courier/emit.py lives outside src/blackbox, so a
    real pip/pipx install (no dev checkout on disk) has to resolve it via
    the copy bundled into the package (pyproject.toml's wheel
    force-include), not the source-tree-relative path. Caught by an actual
    fresh-venv install test — this pins the fix."""
    real_exists = Path.exists

    def fake_exists(self):
        if self.parts[-2:] == ("courier", "emit.py") and "site-packages" not in str(self):
            return False  # simulate: no dev checkout on disk
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)

    resolved = installer._courier_path()
    assert str(resolved).endswith("blackbox/courier/emit.py") or str(resolved).endswith(
        "blackbox\\courier\\emit.py"
    )


def test_install_creates_settings_with_all_events(tmp_path, monkeypatch):
    path = _settings(tmp_path, monkeypatch)

    installer.install()

    settings = json.loads(path.read_text())
    assert set(settings["hooks"].keys()) == set(installer.EVENTS)
    for event in installer.EVENTS:
        entry = settings["hooks"][event][0]
        assert entry["hooks"][0]["command"] == installer._courier_command()
        assert entry["hooks"][0]["async"] is True


def test_install_is_idempotent(tmp_path, monkeypatch):
    path = _settings(tmp_path, monkeypatch)

    installer.install()
    first = json.loads(path.read_text())
    installer.install()
    second = json.loads(path.read_text())

    assert first == second
    for event in installer.EVENTS:
        assert len(second["hooks"][event]) == 1


def test_install_preserves_existing_user_settings(tmp_path, monkeypatch):
    path = _settings(tmp_path, monkeypatch)
    path.write_text(
        json.dumps(
            {
                "theme": "dark",
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "some-other-tool"}],
                        }
                    ]
                },
            }
        )
    )

    installer.install()

    settings = json.loads(path.read_text())
    assert settings["theme"] == "dark"
    pre_tool_entries = settings["hooks"]["PreToolUse"]
    assert len(pre_tool_entries) == 2
    commands = {e["hooks"][0]["command"] for e in pre_tool_entries}
    assert "some-other-tool" in commands
    assert installer._courier_command() in commands


def test_install_backs_up_existing_settings(tmp_path, monkeypatch):
    path = _settings(tmp_path, monkeypatch)
    path.write_text(json.dumps({"theme": "dark"}))

    installer.install()

    backups = list(tmp_path.glob("settings.json.bb-backup-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == {"theme": "dark"}


def test_uninstall_removes_only_courier_entries(tmp_path, monkeypatch):
    path = _settings(tmp_path, monkeypatch)
    installer.install()

    settings = json.loads(path.read_text())
    settings["hooks"]["PreToolUse"].append(
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "some-other-tool"}]}
    )
    path.write_text(json.dumps(settings))

    installer.uninstall()

    settings = json.loads(path.read_text())
    assert "hooks" not in settings or "PreToolUse" not in settings.get("hooks", {}) or all(
        installer._courier_command() not in h["command"]
        for entry in settings["hooks"].get("PreToolUse", [])
        for h in entry["hooks"]
    )
    remaining_commands = {
        h["command"]
        for entry in settings.get("hooks", {}).get("PreToolUse", [])
        for h in entry["hooks"]
    }
    assert "some-other-tool" in remaining_commands


def test_uninstall_on_missing_settings_does_not_crash(tmp_path, monkeypatch):
    _settings(tmp_path, monkeypatch)
    installer.uninstall()  # should not raise

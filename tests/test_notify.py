from unittest.mock import patch

from agentdeck.notify import notifications_enabled, send_notification


def test_notifications_disabled_when_no_config(tmp_path):
    assert notifications_enabled(tmp_path / "does-not-exist.toml") is False


def test_notifications_disabled_by_default_in_written_config(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("[notifications]\nenabled = false\n")
    assert notifications_enabled(config) is False


def test_notifications_enabled_when_set_true(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("[notifications]\nenabled = true\n")
    assert notifications_enabled(config) is True


def test_notifications_disabled_on_invalid_toml(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("not valid [[[ toml")
    assert notifications_enabled(config) is False


def test_notifications_disabled_when_section_missing(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("[pricing.default]\ninput = 1.0\n")
    assert notifications_enabled(config) is False


def test_send_notification_never_raises_on_subprocess_failure():
    with patch("agentdeck.notify.subprocess.run", side_effect=OSError("no such tool")):
        send_notification("title", "message")  # must not raise


def test_send_notification_never_raises_on_unknown_platform():
    with patch("agentdeck.notify.platform.system", return_value="Plan9"):
        send_notification("title", "message")  # must not raise, must not attempt a subprocess


def test_osascript_string_escapes_quotes_and_backslashes():
    from agentdeck.notify import _osascript_string

    result = _osascript_string('say "hi" \\ bye')
    assert result == '"say \\"hi\\" \\\\ bye"'

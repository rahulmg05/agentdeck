from pathlib import Path

import pytest

from agentdeck.ui.app import AgentDeckApp

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_d_key_toggles_dark_light_theme():
    app = AgentDeckApp(sessions_dir=FIXTURES)
    async with app.run_test() as pilot:
        before = app.theme
        await pilot.press("d")
        assert app.theme != before

        await pilot.press("d")
        assert app.theme == before


@pytest.mark.asyncio
async def test_command_palette_includes_builtin_theme_picker():
    app = AgentDeckApp(sessions_dir=FIXTURES)
    async with app.run_test():
        titles = [c.title for c in app.get_system_commands(app.screen)]
        assert "Theme" in titles

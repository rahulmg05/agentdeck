"""`/` search across the current view (design doc Phase 7)."""

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class SearchScreen(ModalScreen[str]):
    CSS = """
    SearchScreen { align: center middle; }
    #search-box { width: 60%; border: thick $primary; background: $panel; padding: 1 2; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, initial_value: str = "") -> None:
        super().__init__()
        self.initial_value = initial_value

    def compose(self):
        with Vertical(id="search-box"):
            yield Label("Search (event text, file paths, commands) — enter to apply, esc to clear")
            yield Input(value=self.initial_value, id="search-input")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    def on_input_submitted(self, message: Input.Submitted) -> None:
        self.dismiss(message.value)

    def action_cancel(self) -> None:
        self.dismiss("")

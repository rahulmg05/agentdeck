"""Detail view: `enter` on a row -> full pretty-printed payload (design doc
Phase 4)."""

import json

from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from agentdeck.events import Event


class DetailScreen(ModalScreen):
    CSS = """
    DetailScreen {
        align: center middle;
    }
    #detail-box {
        width: 90%;
        height: 80%;
        border: thick $primary;
        background: $panel;
        padding: 1 2;
    }
    """

    BINDINGS = [("escape", "dismiss", "Close"), ("enter", "dismiss", "Close"), ("q", "dismiss", "Close")]

    def __init__(self, event: Event) -> None:
        super().__init__()
        self.event = event

    def compose(self):
        with VerticalScroll(id="detail-box"):
            header = f"{self.event.hook_event_name}  |  session {self.event.session_id[:8]}"
            if self.event.agent_id:
                header += f"  |  agent {self.event.agent_id[:8]}"
            yield Static(f"[bold]{header}[/bold]\n")
            pretty = json.dumps(self.event.raw, indent=2, ensure_ascii=False)
            yield Static(pretty)

    def action_dismiss(self) -> None:
        self.dismiss()

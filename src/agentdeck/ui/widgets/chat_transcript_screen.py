"""Chat transcript viewer: full conversation history for a session, with
markdown/code-block rendering (feature-parity item, modeled on the "Chat
Transcript Viewer" in disler/claude-code-hooks-multi-agent-observability)."""

from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

from agentdeck.transcript import ChatMessage

ROLE_LABEL = {"user": "▸ User", "assistant": "● Claude"}


class ChatTranscriptScreen(ModalScreen):
    CSS = """
    ChatTranscriptScreen { align: center middle; }
    #chat-box { width: 90%; height: 85%; border: thick $primary; background: $panel; padding: 1 2; }
    .chat-role-user { color: $accent; text-style: bold; margin-top: 1; }
    .chat-role-assistant { color: $success; text-style: bold; margin-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("q", "dismiss", "Close")]

    def __init__(self, session_label: str, messages: list[ChatMessage]) -> None:
        super().__init__()
        self.session_label = session_label
        self.messages = messages

    def compose(self):
        with VerticalScroll(id="chat-box"):
            yield Static(f"[bold]Chat transcript — {self.session_label}[/bold]\n")
            if not self.messages:
                yield Static("[dim]No chat content available yet for this session.[/dim]")
                return
            for message in self.messages:
                role_class = "chat-role-user" if message.role == "user" else "chat-role-assistant"
                yield Static(ROLE_LABEL.get(message.role, message.role), classes=role_class)
                yield Markdown(message.text)

    def action_dismiss(self) -> None:
        self.dismiss()

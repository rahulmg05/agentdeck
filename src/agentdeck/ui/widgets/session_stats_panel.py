"""Per-session stats panel: tokens, est. cost (design doc Phase 5)."""

from textual.containers import Vertical
from textual.widgets import Static

from agentdeck.events import SessionInfo


class SessionStatsPanel(Vertical):
    def compose(self):
        yield Static(id="session-stats-text")

    def update_for(self, info: SessionInfo | None) -> None:
        text_widget = self.query_one("#session-stats-text", Static)

        if info is None:
            text_widget.update("no session selected")
            return

        total_tokens = (
            info.input_tokens + info.output_tokens + info.cache_write_tokens + info.cache_read_tokens
        )
        text_widget.update(
            f"tokens: {total_tokens:,}  "
            f"(in {info.input_tokens:,} / out {info.output_tokens:,} / "
            f"cache-w {info.cache_write_tokens:,} / cache-r {info.cache_read_tokens:,})   "
            f"est. cost: ${info.cost_usd:.4f}"
        )

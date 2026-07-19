"""Session browser: list past sessions (date, project, duration, cost, fail
count) -> enter to replay (design doc Phase 6)."""

import time

from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from blackbox.reader import SessionSummary


def _format_duration(started_at: float | None, ended_at: float | None) -> str:
    if started_at is None or ended_at is None:
        return "?"
    seconds = max(0, ended_at - started_at)
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


class SessionBrowserScreen(Screen):
    BINDINGS = [("q", "app.quit", "Quit"), ("escape", "app.quit", "Quit")]

    def __init__(self, summaries: list[SessionSummary]) -> None:
        super().__init__()
        self.summaries = summaries

    def compose(self):
        yield Header(show_clock=True)
        yield DataTable(id="session-browser-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#session-browser-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("date", "project", "duration", "events", "fails", "cost")
        for s in self.summaries:
            date_str = (
                time.strftime("%Y-%m-%d %H:%M", time.localtime(s.started_at))
                if s.started_at
                else "?"
            )
            table.add_row(
                date_str,
                s.display_name,
                _format_duration(s.started_at, s.ended_at),
                str(s.event_count),
                str(s.fail_count) if s.fail_count else "",
                f"${s.cost_usd:.4f}" if s.cost_usd else "",
                key=s.session_id,
            )
        table.focus()

    def on_data_table_row_selected(self, message) -> None:
        session_id = str(message.row_key.value)
        self.dismiss(session_id)

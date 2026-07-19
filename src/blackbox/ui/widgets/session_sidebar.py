"""Session sidebar for focused mode: display name, liveness dot in session
color, tool/fail counts (design doc Phase 4)."""

from textual.widgets import DataTable

from blackbox.events import SessionInfo, SessionRegistry

LIVENESS_DOT = {"running": "●", "idle": "○", "ended": "◌"}


class SessionSidebar(DataTable):
    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.add_columns(" ", "session", "tools", "fails", "running")
        self.show_header = True

    def refresh_sessions(
        self, registry: SessionRegistry, now: float, selected_session_id: str | None, open_counts: dict[str, int]
    ) -> None:
        self.clear()
        for info in sorted(registry.all_sessions(), key=lambda s: s.last_event_ts, reverse=True):
            liveness = registry.liveness(info.session_id, now)
            # Dual-color: app bar + session-colored liveness dot.
            dot = (
                f"[{info.app_color}]▎[/{info.app_color}]"
                f"[{info.color}]{LIVENESS_DOT[liveness]}[/{info.color}]"
            )
            name = registry.display_name(info.session_id)
            if info.session_id == selected_session_id:
                name = f"[reverse]{name}[/reverse]"
            running = open_counts.get(info.session_id, 0)
            self.add_row(
                dot,
                name,
                str(info.tool_count),
                str(info.fail_count) if info.fail_count else "",
                str(running) if running else "",
                key=info.session_id,
            )

    @staticmethod
    def sort_key(info: SessionInfo) -> float:
        return -info.last_event_ts

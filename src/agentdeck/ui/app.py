"""AgentDeck console: firehose (Phase 3) + cockpit layout (Phase 4). Three
view modes share one reader -> dispatcher pipeline and one continuously
updated set of widgets; switching modes only toggles which widgets are
visible, so no state is lost in the switch (design doc Phase 4 checkpoint).
"""

import asyncio
import time
from pathlib import Path

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Container, Grid, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from agentdeck.events import Event, SessionRegistry, parse_line
from agentdeck.notify import notifications_enabled, send_notification
from agentdeck.pairing import PairTracker
from agentdeck.pricing import ensure_config_exists, estimate_cost_usd, load_pricing
from agentdeck.reader import DEFAULT_SESSIONS_DIR, Reader, load_session_events, scan_sessions
from agentdeck.transcript import TranscriptReader, build_chat_transcript
from agentdeck.ui.theme import icon_for, summarize
from agentdeck.ui.widgets.chat_transcript_screen import ChatTranscriptScreen
from agentdeck.ui.widgets.detail_screen import DetailScreen
from agentdeck.ui.widgets.focused_timeline import FocusedTimeline
from agentdeck.ui.widgets.search_screen import SearchScreen
from agentdeck.ui.widgets.session_browser_screen import SessionBrowserScreen
from agentdeck.ui.widgets.session_sidebar import SessionSidebar
from agentdeck.ui.widgets.session_stats_panel import SessionStatsPanel
from agentdeck.ui.widgets.timeline_log import TimelineLog

RUNNING_WINDOW_S = 60.0
WALL_MAX_PANES = 4
TRANSCRIPT_POLL_INTERVAL_S = 2.0
LONG_TASK_NOTIFY_THRESHOLD_MS = 30_000

# Phase 6: replay speeds. None means "max" — no throttling at all. Even at
# 1x, a real multi-minute gap between two events is capped so replay doesn't
# sit idle for the literal original duration.
REPLAY_SPEEDS: list[float | None] = [1.0, 5.0, 20.0, None]
MAX_REPLAY_GAP_S = 3.0


class AgentDeckApp(App):
    TITLE = "AgentDeck"
    CSS = """
    #stats { height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    #focused-layout { height: 1fr; }
    #sidebar { width: 34; }
    #focused-timeline { width: 1fr; }
    #timeline { background: $surface; height: 1fr; }
    #wall-layout { height: 1fr; }
    #wall-grid { grid-size: 2 2; height: 1fr; }
    .wall-pane { border: round $primary-background; height: 1fr; }
    #wall-more { height: 1; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "clear_view", "Clear"),
        ("p", "toggle_pause", "Pause"),
        ("end", "jump_to_end", "Resume auto-scroll"),
        ("0", "clear_filter", "Show all"),
        ("1", "filter_session(1)", "Filter 1"),
        ("2", "filter_session(2)", "Filter 2"),
        ("3", "filter_session(3)", "Filter 3"),
        ("4", "filter_session(4)", "Filter 4"),
        ("5", "filter_session(5)", "Filter 5"),
        ("6", "filter_session(6)", "Filter 6"),
        ("7", "filter_session(7)", "Filter 7"),
        ("8", "filter_session(8)", "Filter 8"),
        ("9", "filter_session(9)", "Filter 9"),
        ("s", "set_mode('focused')", "Focused"),
        ("f", "set_mode('firehose')", "Firehose"),
        ("w", "set_mode('wall')", "Wall"),
        # priority=True: Screen binds bare "tab" to app.focus_next itself,
        # and (being closer to the focused widget in the DOM chain) wins
        # over a same-priority App binding, so ours has to jump the queue.
        Binding("tab", "cycle_session", "Next session", priority=True),
        ("g", "toggle_focus_follow", "Focus-follow"),
        ("enter", "show_detail", "Detail"),
        ("t", "show_chat_transcript", "Chat transcript"),
        Binding("space", "replay_toggle_pause", "Play/Pause", priority=True),
        Binding("left", "replay_seek(-1)", "Seek back", priority=True),
        Binding("right", "replay_seek(1)", "Seek forward", priority=True),
        ("]", "replay_speed_up", "Speed +"),
        ("[", "replay_speed_down", "Speed -"),
        ("/", "search", "Search"),
        ("e", "toggle_errors_only", "Errors only"),
        ("d", "toggle_dark", "Toggle dark/light"),
    ]

    COMMAND_PALETTE_BINDING = "ctrl+k"

    mode: reactive[str] = reactive("focused")

    def __init__(
        self,
        sessions_dir: Path = DEFAULT_SESSIONS_DIR,
        replay_events: list[Event] | None = None,
        show_browser: bool = False,
    ) -> None:
        super().__init__()
        self.reader = Reader(sessions_dir)
        self.sessions_dir = sessions_dir
        self.registry = SessionRegistry()
        self.pair_tracker = PairTracker()
        self.paused = False
        self.filter_session_id: str | None = None
        self.event_count = 0
        self._session_order: list[str] = []
        self._all_events: list[Event] = []

        self.selected_session_id: str | None = None
        self.focus_follow = True
        self._wall_panes: dict[str, TimelineLog] = {}
        self._wall_session_ids: list[str] = []

        # Phase 5: token/cost tracking.
        ensure_config_exists()
        self.pricing = load_pricing()
        self._transcript_readers: dict[str, TranscriptReader] = {}

        # Phase 7: desktop notifications — optional, config-gated, off by default.
        self.notify_enabled = notifications_enabled()

        # Phase 6: replay mode. Live mode (the default) ignores all of this.
        self.show_browser = show_browser
        self.is_replay = replay_events is not None
        self.replay_events: list[Event] = replay_events or []
        self.replay_position = 0
        self.replay_paused = False
        self.replay_finished = False
        self.replay_speed_index = 0

        # Phase 7: search + filters, applied wherever events are rendered.
        self.search_query = ""
        self.event_type_filter: str | None = None
        self.errors_only = False

    def get_system_commands(self, screen: Screen):
        yield from super().get_system_commands(screen)

        yield SystemCommand("Mode: focused", "Sidebar + per-session timeline", lambda: self.action_set_mode("focused"))
        yield SystemCommand("Mode: firehose", "Flat chronological stream of every session", lambda: self.action_set_mode("firehose"))
        yield SystemCommand("Mode: wall", "Tile up to 4 sessions at once", lambda: self.action_set_mode("wall"))
        yield SystemCommand("Toggle pause", "Freeze/resume the live view", self.action_toggle_pause)
        yield SystemCommand("Toggle focus-follow", "Auto-jump to the most recently active session", self.action_toggle_focus_follow)
        yield SystemCommand("Errors only", "Show only failure events", self.action_toggle_errors_only)
        yield SystemCommand("Clear event-type filter", "Show all event types again", lambda: self.set_event_type_filter(None))
        yield SystemCommand(
            "Chat transcript", "Full conversation for the selected session", self.action_show_chat_transcript
        )

        seen_types = sorted({e.hook_event_name for e in self._all_events})
        for event_type in seen_types:
            yield SystemCommand(
                f"Filter: {event_type} only",
                "Show only this event type",
                lambda et=event_type: self.set_event_type_filter(et),
                discover=False,
            )

        for session_id in self._session_order:
            name = self.registry.display_name(session_id)
            yield SystemCommand(
                f"Jump to session: {name}",
                session_id,
                lambda sid=session_id: self._jump_to_session(sid),
                discover=False,
            )

    def _jump_to_session(self, session_id: str) -> None:
        self.selected_session_id = session_id
        self.focus_follow = False
        self.mode = "focused"
        self._reload_focused_timeline()
        self._refresh_sidebar()
        self._refresh_stats()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="stats")
        with Horizontal(id="focused-layout"):
            yield SessionSidebar(id="sidebar")
            with Vertical():
                yield FocusedTimeline(id="focused-timeline")
                yield SessionStatsPanel(id="session-stats-panel")
        yield TimelineLog(id="timeline", wrap=False, markup=True, highlight=False, auto_scroll=True)
        yield Container(id="wall-layout")
        yield Footer()

    async def on_mount(self) -> None:
        self._apply_mode_visibility()

        if self.show_browser:
            # push_screen_wait requires an active worker context, so the
            # browse-then-replay handoff has to happen inside one rather
            # than directly in on_mount.
            self.run_worker(self._browse_then_replay(), exclusive=True, group="browse")
            return

        if self.is_replay:
            self._refresh_stats()
            self.run_worker(self._replay_loop(), exclusive=True, group="replay")
            return

        for event in self.reader.load_history():
            self._handle_event(event, render=False)
        self._rerender_filtered()
        self._reload_focused_timeline()
        if self.mode == "wall":
            self._rebuild_wall()
        self._refresh_stats()
        self._refresh_sidebar()
        self._refresh_session_stats_panel()
        self.run_worker(self._watch_loop(), exclusive=True, group="watch")
        self._poll_transcripts()
        self.set_interval(TRANSCRIPT_POLL_INTERVAL_S, self._poll_transcripts)

    async def _watch_loop(self) -> None:
        async for event in self.reader.watch():
            self._handle_event(event)
            self._refresh_stats()
            self._refresh_sidebar()

    # ---- replay (Phase 6) ------------------------------------------------

    async def _browse_then_replay(self) -> None:
        summaries = scan_sessions(self.sessions_dir, self.pricing)
        session_id = await self.push_screen_wait(SessionBrowserScreen(summaries))
        if session_id is None:
            self.exit()
            return
        self.is_replay = True
        self.replay_events = load_session_events(self.sessions_dir / session_id)
        self._refresh_stats()
        self.run_worker(self._replay_loop(), exclusive=True, group="replay")

    async def _replay_loop(self) -> None:
        while self.replay_position < len(self.replay_events):
            if self.replay_paused:
                await asyncio.sleep(0.1)
                continue

            event = self.replay_events[self.replay_position]
            self._handle_event(event)
            self._refresh_stats()
            self._refresh_sidebar()
            self.replay_position += 1

            if self.replay_position < len(self.replay_events):
                speed = REPLAY_SPEEDS[self.replay_speed_index]
                if speed is not None:
                    next_event = self.replay_events[self.replay_position]
                    real_delay = max(0.0, next_event.ad_ts - event.ad_ts)
                    delay = min(real_delay / speed, MAX_REPLAY_GAP_S)
                    if delay > 0:
                        await asyncio.sleep(delay)

        self.replay_finished = True
        self._refresh_stats()

    def action_replay_toggle_pause(self) -> None:
        if not self.is_replay:
            return
        self.replay_paused = not self.replay_paused
        self._refresh_stats()

    def action_replay_speed_up(self) -> None:
        if not self.is_replay:
            return
        self.replay_speed_index = min(len(REPLAY_SPEEDS) - 1, self.replay_speed_index + 1)
        self._refresh_stats()

    def action_replay_speed_down(self) -> None:
        if not self.is_replay:
            return
        self.replay_speed_index = max(0, self.replay_speed_index - 1)
        self._refresh_stats()

    def action_replay_seek(self, direction: int) -> None:
        if not self.is_replay or not self.replay_events:
            return
        chunk = max(1, len(self.replay_events) // 10)
        new_position = max(0, min(len(self.replay_events), self.replay_position + direction * chunk))
        self._replay_jump_to(new_position)

    def _replay_jump_to(self, position: int) -> None:
        """Seeking can't "un-happen" already-applied state (registry, pair
        tracker, widgets), so the only correct way to scrub is to reset
        everything and instantly replay up to the new position, then resume
        normal-speed playback from there."""
        self.registry = SessionRegistry()
        self.pair_tracker = PairTracker()
        self.event_count = 0
        self._session_order = []
        self._all_events = []
        self.selected_session_id = None
        self._transcript_readers = {}

        self.query_one("#timeline", TimelineLog).clear()
        self.query_one("#focused-timeline", FocusedTimeline).clear_timeline()
        for pane in self._wall_panes.values():
            pane.remove()
        self._wall_panes.clear()
        self._wall_session_ids = []

        for event in self.replay_events[:position]:
            self._handle_event(event, render=False)
        self.replay_position = position
        self.replay_finished = False

        self._rerender_filtered()
        self._reload_focused_timeline()
        if self.mode == "wall":
            self._rebuild_wall()

        self._refresh_stats()
        self._refresh_sidebar()
        self._refresh_session_stats_panel()

    # ---- ingest -----------------------------------------------------

    def _matches_filters(self, event: Event) -> bool:
        """Search/event-type/errors-only filters (design doc Phase 7) — these
        only ever affect what's *rendered*; registry/pair-tracker bookkeeping
        always sees every event, same principle as pause (3.1/Phase 3)."""
        if self.errors_only and event.hook_event_name not in ("PostToolUseFailure", "StopFailure"):
            return False
        if self.event_type_filter and event.hook_event_name != self.event_type_filter:
            return False
        if self.search_query:
            haystack = " ".join(
                [
                    event.hook_event_name,
                    event.tool_name or "",
                    summarize(event),
                ]
            ).lower()
            if self.search_query.lower() not in haystack:
                return False
        return True

    def _maybe_notify(self, event: Event) -> None:
        """Best-effort desktop notification (design doc Phase 7) — never
        raises, and only fires in live mode (replay is about reviewing the
        past, not "something just happened")."""
        session_label = self.registry.display_name(event.session_id)

        if event.hook_event_name == "Notification":
            message = event.raw.get("message") or "Claude Code notification"
            send_notification(f"AgentDeck — {session_label}", str(message))
        elif event.hook_event_name == "PostToolUse":
            duration = event.raw.get("duration_ms")
            if isinstance(duration, (int, float)) and duration >= LONG_TASK_NOTIFY_THRESHOLD_MS:
                tool = event.tool_name or "tool"
                send_notification(
                    f"AgentDeck — {session_label}",
                    f"{tool} finished after {duration / 1000:.0f}s",
                )

    def _handle_event(self, event: Event, render: bool = True) -> None:
        """`render=False` is for bulk loading (initial history, replay
        seek): bookkeeping only, no widget updates. RichLog/DataTable have
        no cheap "insert at top" for many rows at once, so bulk loads
        instead call this with render=False for every event and then do
        ONE reversed-order bulk render afterward (_rerender_filtered /
        _reload_focused_timeline / _rebuild_wall) — see timeline_log.py's
        module docstring. `render=True` (the default) is for a single
        live/replay event and updates widgets incrementally, moving the
        new line/row to the top as it arrives.
        """
        self.registry.observe(event)
        self.pair_tracker.observe(event)
        self.event_count += 1
        self._all_events.append(event)

        # Bulk-loaded history is old news by definition — only genuinely
        # live events should trigger a desktop notification.
        if self.notify_enabled and not self.is_replay and render:
            self._maybe_notify(event)

        is_new_session = event.session_id not in self._session_order
        if is_new_session:
            self._session_order.append(event.session_id)

        session_switched = False
        if self.selected_session_id is None:
            self.selected_session_id = event.session_id
            session_switched = True
        elif self.focus_follow and event.session_id != self.selected_session_id:
            self.selected_session_id = event.session_id
            session_switched = True

        if not render:
            return

        if session_switched:
            self._reload_focused_timeline()
        elif event.session_id == self.selected_session_id and self._matches_filters(event):
            self.query_one("#focused-timeline", FocusedTimeline).add_event_live(event, self.registry)

        if self.mode == "wall":
            self._sync_wall(event)

        if self.paused:
            return
        if self.filter_session_id and event.session_id != self.filter_session_id:
            return
        if not self._matches_filters(event):
            return
        self.query_one("#timeline", TimelineLog).write_newest_first(self._render_firehose_line(event))

    def _render_firehose_line(self, event: Event) -> str:
        info = self.registry.get(event.session_id)
        color = info.color if info else "#ffffff"
        app_color = info.app_color if info else "#ffffff"
        name = self.registry.display_name(event.session_id)
        ts = time.strftime("%H:%M:%S", time.localtime(event.ad_ts)) if event.ad_ts else "--:--:--"
        icon = icon_for(event)
        summary = summarize(event)
        truncated_marker = " [dim]\\[truncated][/dim]" if event.ad_truncated else ""
        is_failure = event.hook_event_name in ("PostToolUseFailure", "StopFailure")
        icon_markup = f"[bold red]{icon}[/bold red]" if is_failure else icon
        lane_marker = "  ↳ " if event.agent_id else ""

        # Dual-color system: app color (project) + session color, as two
        # adjacent bars — sessions in the same project share the first bar,
        # each session keeps its own distinct second bar.
        return (
            f"[dim]{ts}[/dim] [{app_color}]▎[/{app_color}][{color}]▍{name:<16}[/{color}] {lane_marker}"
            f"{icon_markup} [bold]{event.hook_event_name}[/bold] {summary}{truncated_marker}"
        )

    # ---- stats / sidebar ---------------------------------------------

    def _refresh_stats(self) -> None:
        now = time.time()
        sessions = self.registry.all_sessions()
        running = sum(1 for s in sessions if self.registry.liveness(s.session_id, now) == "running")
        stale = sum(
            1
            for s in sessions
            if self.registry.liveness(s.session_id, now) == "running"
            and now - s.last_event_ts > RUNNING_WINDOW_S
        )
        pause_marker = " [PAUSED]" if self.paused else ""
        follow_marker = "" if self.focus_follow else " [no-follow]"
        filter_marker = (
            f" | filter: {self.registry.display_name(self.filter_session_id)}"
            if self.filter_session_id
            else ""
        )
        total_cost = sum(s.cost_usd for s in sessions)
        stats = self.query_one("#stats", Static)

        if self.is_replay:
            speed = REPLAY_SPEEDS[self.replay_speed_index]
            speed_label = "max" if speed is None else f"{speed:g}x"
            state = "finished" if self.replay_finished else ("paused" if self.replay_paused else "playing")
            stats.update(
                f"REPLAY [{state}] {speed_label} | position: {self.replay_position}/{len(self.replay_events)} "
                f"| events: {self.event_count} | est. cost: ${total_cost:.4f} | mode: {self.mode}"
            )
            return

        stats.update(
            f"events: {self.event_count} | sessions: {len(sessions)} ({running} running"
            f"{', ' + str(stale) + ' stale' if stale else ''}) | dropped: "
            f"{self.reader.dropped_lines} | est. cost: ${total_cost:.4f}"
            f"{pause_marker}{follow_marker}{filter_marker} | mode: {self.mode}"
        )

    def _refresh_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar", SessionSidebar)
        open_counts: dict[str, int] = {}
        for call in self.pair_tracker.open_calls():
            open_counts[call.session_id] = open_counts.get(call.session_id, 0) + 1
        sidebar.refresh_sessions(self.registry, time.time(), self.selected_session_id, open_counts)

    # ---- token/cost (Phase 5) -------------------------------------------

    def _poll_transcripts(self) -> None:
        now = time.time()
        for info in self.registry.all_sessions():
            if not info.transcript_path:
                continue
            reader = self._transcript_readers.get(info.session_id)
            if reader is None:
                reader = TranscriptReader(info.transcript_path)
                self._transcript_readers[info.session_id] = reader
            for usage in reader.read_new_usage():
                cost = estimate_cost_usd(usage, self.pricing)
                self.registry.add_usage(
                    info.session_id,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_write_tokens=usage.cache_creation_input_tokens,
                    cache_read_tokens=usage.cache_read_input_tokens,
                    cost_usd=cost,
                    bucket_now=now,
                )
        self._refresh_stats()
        self._refresh_session_stats_panel()

    def _refresh_session_stats_panel(self) -> None:
        panel = self.query_one("#session-stats-panel", SessionStatsPanel)
        info = self.registry.get(self.selected_session_id) if self.selected_session_id else None
        series = (
            self.registry.tokens_per_minute_series(self.selected_session_id, time.time())
            if self.selected_session_id
            else []
        )
        panel.update_for(info, series)

    # ---- focused mode --------------------------------------------------

    def _reload_focused_timeline(self) -> None:
        table = self.query_one("#focused-timeline", FocusedTimeline)
        table.clear_timeline()
        for event in reversed(self._all_events):
            if event.session_id == self.selected_session_id and self._matches_filters(event):
                table.add_event(event, self.registry)
        table.scroll_home(animate=False)
        self._refresh_session_stats_panel()

    def on_data_table_row_selected(self, message) -> None:
        if message.data_table.id == "sidebar":
            session_id = str(message.row_key.value)
            self.selected_session_id = session_id
            self.focus_follow = False
            self._reload_focused_timeline()
            self._refresh_sidebar()
            self._refresh_stats()
        elif message.data_table.id == "focused-timeline":
            self.action_show_detail()

    def on_focused_timeline_user_scrolled(self, message: FocusedTimeline.UserScrolled) -> None:
        if self.focus_follow:
            self.focus_follow = False
            self._refresh_stats()

    def action_cycle_session(self) -> None:
        if not self._session_order:
            return
        self.focus_follow = False
        if self.selected_session_id not in self._session_order:
            self.selected_session_id = self._session_order[0]
        else:
            idx = self._session_order.index(self.selected_session_id)
            self.selected_session_id = self._session_order[(idx + 1) % len(self._session_order)]
        self._reload_focused_timeline()
        self._refresh_sidebar()
        self._refresh_stats()

    def action_toggle_focus_follow(self) -> None:
        self.focus_follow = not self.focus_follow
        self._refresh_stats()

    def action_show_detail(self) -> None:
        table = self.query_one("#focused-timeline", FocusedTimeline)
        if table.cursor_row is None:
            return
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return
        event = table.event_for_row_key(str(row_key.value))
        if event is not None:
            self.push_screen(DetailScreen(event))

    def action_show_chat_transcript(self) -> None:
        if not self.selected_session_id:
            return
        info = self.registry.get(self.selected_session_id)
        user_prompt_events = [
            e
            for e in self._all_events
            if e.session_id == self.selected_session_id and e.hook_event_name == "UserPromptSubmit"
        ]
        transcript_path = Path(info.transcript_path) if info and info.transcript_path else None
        messages = build_chat_transcript(user_prompt_events, transcript_path)
        label = self.registry.display_name(self.selected_session_id)
        self.push_screen(ChatTranscriptScreen(label, messages))

    # ---- wall mode ------------------------------------------------------

    def _top_sessions(self, limit: int) -> list[str]:
        sessions = sorted(self.registry.all_sessions(), key=lambda s: s.last_event_ts, reverse=True)
        return [s.session_id for s in sessions[:limit]]

    def _rebuild_wall(self) -> None:
        container = self.query_one("#wall-layout", Container)
        container.remove_children()
        self._wall_panes.clear()

        top = self._top_sessions(WALL_MAX_PANES)
        self._wall_session_ids = top
        rest_count = max(0, len(self._session_order) - len(top))

        grid = Grid(id="wall-grid")
        container.mount(grid)
        for session_id in top:
            pane = TimelineLog(classes="wall-pane", wrap=False, markup=True, highlight=False)
            grid.mount(pane)
            self._wall_panes[session_id] = pane
            for event in reversed(self._all_events):
                if event.session_id == session_id and self._matches_filters(event):
                    pane.write(self._render_firehose_line(event), scroll_end=False)
            pane.scroll_home(animate=False)

        if rest_count:
            container.mount(Static(f"+{rest_count} more session(s) not shown", id="wall-more"))

    def _sync_wall(self, event: Event) -> None:
        current_top = self._top_sessions(WALL_MAX_PANES)
        if current_top != self._wall_session_ids:
            self._rebuild_wall()
            return
        if not self._matches_filters(event):
            return
        pane = self._wall_panes.get(event.session_id)
        if pane is not None:
            pane.write_newest_first(self._render_firehose_line(event))

    # ---- mode switching --------------------------------------------------

    def watch_mode(self, old_mode: str, new_mode: str) -> None:
        if not self.is_mounted:
            return
        self._apply_mode_visibility()
        if new_mode == "wall":
            self._rebuild_wall()
        self._refresh_stats()

    def _apply_mode_visibility(self) -> None:
        self.query_one("#focused-layout").display = self.mode == "focused"
        self.query_one("#timeline", TimelineLog).display = self.mode == "firehose"
        self.query_one("#wall-layout", Container).display = self.mode == "wall"

        # A hidden-but-still-focused widget silently swallows key bindings
        # meant for whatever's actually on screen (e.g. RichLog/DataTable
        # both bind "end" at the widget level — see their own comments) —
        # so focus has to move with visibility, not just displayed content.
        if self.mode == "focused":
            self.query_one("#focused-timeline", FocusedTimeline).focus()
        elif self.mode == "firehose":
            self.query_one("#timeline", TimelineLog).focus()

    def action_set_mode(self, mode: str) -> None:
        self.mode = mode

    # ---- misc actions --------------------------------------------------

    def action_clear_view(self) -> None:
        self.query_one("#timeline", TimelineLog).clear()

    def action_jump_to_end(self) -> None:
        if self.mode == "focused":
            self.query_one("#focused-timeline", FocusedTimeline).jump_to_end()
        else:
            self.query_one("#timeline", TimelineLog).jump_to_end()

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        if not self.paused:
            self._rerender_filtered()
        self._refresh_stats()

    def action_filter_session(self, n: int) -> None:
        if n - 1 < len(self._session_order):
            self.filter_session_id = self._session_order[n - 1]
            self._rerender_filtered()

    def action_clear_filter(self) -> None:
        self.filter_session_id = None
        self._rerender_filtered()

    # ---- search / filters (Phase 7) --------------------------------------

    def action_search(self) -> None:
        def apply_search(query: str | None) -> None:
            self.search_query = query or ""
            self._apply_filters_everywhere()

        self.push_screen(SearchScreen(self.search_query), apply_search)

    def action_toggle_errors_only(self) -> None:
        self.errors_only = not self.errors_only
        self._apply_filters_everywhere()

    def set_event_type_filter(self, event_type: str | None) -> None:
        self.event_type_filter = event_type
        self._apply_filters_everywhere()

    def _apply_filters_everywhere(self) -> None:
        self._rerender_filtered()
        if self.selected_session_id:
            self._reload_focused_timeline()
        if self.mode == "wall":
            self._rebuild_wall()
        self._refresh_stats()

    def _rerender_filtered(self) -> None:
        log = self.query_one("#timeline", TimelineLog)
        log.clear()
        for event in reversed(self._all_events):
            if self.filter_session_id and event.session_id != self.filter_session_id:
                continue
            if not self._matches_filters(event):
                continue
            log.write(self._render_firehose_line(event), scroll_end=False)
        log.scroll_home(animate=False)
        self._refresh_stats()


def run_app(
    sessions_dir: Path | None = None,
    replay_session: str | None = None,
    replay_file: str | None = None,
    replay_browse: bool = False,
) -> None:
    target = sessions_dir or DEFAULT_SESSIONS_DIR

    if replay_session:
        events = load_session_events(target / replay_session)
        AgentDeckApp(sessions_dir=target, replay_events=events).run()
        return

    if replay_file:
        path = Path(replay_file)
        events = [
            e
            for e in (parse_line(line, path) for line in path.read_text().splitlines() if line.strip())
            if e is not None
        ]
        events.sort(key=lambda e: e.ad_ts)
        AgentDeckApp(sessions_dir=target, replay_events=events).run()
        return

    if replay_browse:
        AgentDeckApp(sessions_dir=target, show_browser=True).run()
        return

    AgentDeckApp(sessions_dir=target).run()

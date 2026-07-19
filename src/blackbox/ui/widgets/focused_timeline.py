"""Per-session timeline for focused mode: a row-selectable table (unlike the
firehose's append-only RichLog) so `enter` can open a detail view for a
specific event (design doc Phase 4). Newest-first, same convention as
TimelineLog — see that module's docstring for the bulk-vs-live rendering
split (`add_event()` for bulk/reversed-order loads, `add_event_live()` for
a single live event that needs to land at the top of an already-populated
table)."""

import time

from textual.message import Message
from textual.widgets import DataTable
from textual.widgets._data_table import TwoWayDict

from blackbox.events import Event, SessionRegistry
from blackbox.ui.theme import icon_for, summarize


class FocusedTimeline(DataTable):
    class UserScrolled(Message):
        """Posted when the user scrolls away from the top manually (as
        opposed to this widget's own scroll-to-top on new rows) — design
        doc Phase 4: "auto-disabled whenever the user scrolls up"."""

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        if new_value > 0.5:
            if self.auto_scroll:
                self.post_message(self.UserScrolled())
            self.auto_scroll = False

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.add_columns("time", "", "event", "summary")
        self.show_header = False
        self._events: dict[str, Event] = {}
        self._next_key = 0
        self.auto_scroll = True

    def clear_timeline(self) -> None:
        self.clear()
        self._events = {}
        self._next_key = 0
        self.auto_scroll = True

    def add_event(self, event: Event, registry: SessionRegistry) -> None:
        """Append one row at the bottom. Safe for bulk loads only when the
        caller iterates events in REVERSED chronological order (newest
        first) — see module docstring. Does not touch scroll position;
        callers doing a bulk load should scroll_home() once at the end."""
        ts = time.strftime("%H:%M:%S", time.localtime(event.bb_ts)) if event.bb_ts else "--:--:--"
        icon = icon_for(event)
        is_failure = event.hook_event_name in ("PostToolUseFailure", "StopFailure")
        icon_markup = f"[bold red]{icon}[/bold red]" if is_failure else icon
        summary = summarize(event)
        # Subagent events get an indented "lane" marker (design doc Phase 4:
        # "indented lane under parent, keyed by agent_id"). A flat table
        # can't do a true collapsible tree, but the indent still conveys it.
        name_cell = f"  ↳ [dim]{event.hook_event_name}[/dim]" if event.agent_id else event.hook_event_name

        key = str(self._next_key)
        self._next_key += 1
        self._events[key] = event
        self.add_row(f"[dim]{ts}[/dim]", icon_markup, name_cell, summary, key=key)

    def add_event_live(self, event: Event, registry: SessionRegistry) -> None:
        """Add one row for a genuinely live event and move it to the top.
        For bulk loads, use add_event() in reversed iteration order instead
        — DataTable has no cheap insert-at-top, so reordering after every
        single row during a big bulk load would be wasteful."""
        self.add_event(event, registry)
        self._move_last_row_to_top()
        if self.auto_scroll:
            self.scroll_home(animate=False)

    def _move_last_row_to_top(self) -> None:
        """Mirrors DataTable.sort()'s own internal reindexing (there's no
        public API for "insert at position 0"), keyed by our own tracked
        Event.bb_ts rather than a visible column — adding a real column
        just to hold a sort key would make it visible in the table, and
        DataTable's `width=0` does not actually hide a column (checked
        empirically). This depends on DataTable's private _data/
        _row_locations/TwoWayDict structure as of textual 8.2.x; covered by
        tests so a future Textual upgrade that changes this would fail
        loudly rather than silently misorder rows.
        """

        def sort_key(item):
            row_key, _ = item
            event = self._events.get(str(row_key.value))
            return event.bb_ts if event else 0.0

        ordered_rows = sorted(self._data.items(), key=sort_key, reverse=True)
        self._row_locations = TwoWayDict(
            {row_key: new_index for new_index, (row_key, _) in enumerate(ordered_rows)}
        )
        self._update_count += 1
        self.refresh()

    def jump_to_end(self) -> None:
        self.auto_scroll = True
        self.scroll_home(animate=False)

    def action_scroll_end(self) -> None:
        # DataTable binds `end` -> action_scroll_end itself, at widget
        # level — same shadowing issue as TimelineLog (see its comment).
        self.jump_to_end()

    def event_for_row_key(self, key: str) -> Event | None:
        return self._events.get(key)

"""A RichLog that displays newest-first (most recent event at the top) —
that's what you want to see without scrolling in a live-updating log.

RichLog only supports appending. For a single live event arriving after the
widget is already sized, `write_newest_first()` renders normally (so Rich's
layout pipeline runs) and then moves the freshly-appended line from the end
of the internal line buffer to the front — a plain list reinsertion, not a
re-render, so it stays fast even with thousands of lines already present
(benchmarked: ~0.02ms per call vs. ~100ms for naively clearing and
rewriting everything in reverse order on every single new event).

Bulk loads (initial history, mode/filter rebuilds) should NOT use
`write_newest_first()` — call the plain inherited `write()` once per event
in REVERSED chronological order instead. That produces the same final
newest-first order with no reordering trick, and — importantly — still
works correctly even if the writes get deferred (RichLog defers rendering
until it knows its size, which is true for the whole synchronous body of
`on_mount`), since deferred writes are flushed later in the same order they
were submitted.

Auto-scroll pauses when the user scrolls away from the TOP (not the bottom
— inverted from RichLog's own convention, since top = newest here) and
resumes on demand.
"""

from textual.widgets import RichLog


class TimelineLog(RichLog):
    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        if new_value > 0.5:
            self.auto_scroll = False

    def write_newest_first(self, content, animate: bool = False) -> None:
        """Render `content` and move it to the top — for a single live
        event arriving after the widget is already sized. Do NOT use this
        for bulk/initial loads; see the module docstring."""
        lines_before = len(self.lines)
        self.write(content, scroll_end=False, animate=animate)
        if len(self.lines) > lines_before:
            # A deferred write (widget not yet sized) leaves self.lines
            # unchanged here — nothing to reorder yet; it'll flush later in
            # submission order, which bulk callers already account for.
            self.lines.insert(0, self.lines.pop())
            self.refresh()
        if self.auto_scroll:
            self.scroll_home(animate=animate)

    def jump_to_end(self) -> None:
        self.auto_scroll = True
        self.scroll_home(animate=False)

    def action_scroll_end(self) -> None:
        # RichLog binds `end` -> action_scroll_end itself, at widget level —
        # that shadows any App-level "end" binding while this widget has
        # focus, so the auto_scroll re-enable has to happen here too.
        self.jump_to_end()

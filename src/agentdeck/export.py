"""agentdeck export <session> -> self-contained HTML timeline (design doc
Phase 6). No external assets — everything inlined so the file is shareable
on its own.
"""

import html
import time
from pathlib import Path

from agentdeck.reader import DEFAULT_SESSIONS_DIR, load_session_events
from agentdeck.ui.theme import icon_for, summarize

TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>AgentDeck session {session_id}</title>
<style>
body {{ font-family: ui-monospace, "SF Mono", Menlo, monospace; background:#1e1e2e; color:#cdd6f4;
        margin:0; padding:1.5rem; }}
h1 {{ font-size: 1rem; color: #89b4fa; font-weight: 600; }}
.row {{ display:flex; gap:0.75rem; padding:2px 4px; border-radius:3px; align-items: baseline; }}
.row:hover {{ background:#313244; }}
.row.failure {{ color:#f38ba8; }}
.row.subagent {{ padding-left: 2.5rem; opacity:0.85; }}
.ts {{ color:#6c7086; width:5rem; flex-shrink:0; }}
.icon {{ width:1.5rem; flex-shrink:0; }}
.name {{ font-weight:bold; width:14rem; flex-shrink:0; }}
.summary {{ color:#a6adc8; white-space:pre; overflow:hidden; text-overflow:ellipsis; }}
</style></head>
<body>
<h1>AgentDeck session {session_id} &mdash; {count} events</h1>
<div class="timeline">
{rows}
</div>
</body></html>
"""

ROW_TEMPLATE = (
    '<div class="row {row_class}">'
    '<span class="ts">{ts}</span>'
    '<span class="icon">{icon}</span>'
    '<span class="name">{name}</span>'
    '<span class="summary">{summary}</span>'
    "</div>"
)


def export_session(
    session_id: str,
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
    output_path: Path | None = None,
) -> Path:
    session_dir = sessions_dir / session_id
    events = load_session_events(session_dir)
    if output_path is None:
        output_path = Path(f"agentdeck-{session_id}.html")

    rows = []
    for event in events:
        ts = time.strftime("%H:%M:%S", time.localtime(event.ad_ts)) if event.ad_ts else "--:--:--"
        is_failure = event.hook_event_name in ("PostToolUseFailure", "StopFailure")
        classes = " ".join(
            filter(None, ["failure" if is_failure else "", "subagent" if event.agent_id else ""])
        )
        rows.append(
            ROW_TEMPLATE.format(
                row_class=classes,
                ts=html.escape(ts),
                icon=html.escape(icon_for(event)),
                name=html.escape(event.hook_event_name),
                summary=html.escape(summarize(event)),
            )
        )

    output_path.write_text(
        TEMPLATE.format(session_id=html.escape(session_id), rows="\n".join(rows), count=len(events))
    )
    return output_path

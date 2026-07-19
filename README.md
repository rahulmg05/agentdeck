# AgentDeck

Agentdeck is a recorder that silently captures and durably logs every
lifecycle event, prompt, and tool call from your agentic coding sessions.
It features a rich terminal UI that provides a live view of your active
sessions, complete with real-time tool durations, token tracking, and the
ability to replay historical interactions.

As off today it supports, Claude Code's activity — prompts, tool calls,
file edits, subagents, token spend — normally only exists as scrolling
chat text, gone the moment the terminal closes. AgentDeck fixes that.
It's two cooperating pieces:

- **Recorder** — a tiny stdlib-only hook script that Claude Code calls on
  every lifecycle event (prompt submitted, tool about to run, tool
  finished, session ended, subagent spawned, ...). Each event is appended
  as one JSON line to a durable per-session log on disk.
- **Console** — a Textual TUI that tails those logs and renders them live:
  a colored multi-session firehose, a per-session cockpit view with tool
  durations and token/cost tracking, a tiled wall of every active session,
  and full replay of any past session at up to max speed.

Recording is always on, for every Claude Code session on the machine, with
zero effort after a one-time install. If the console isn't running, events
still land in the log — the console just catches up on next launch, so
nothing is ever lost.

![AgentDeck focused-mode cockpit: session sidebar, event timeline with tool durations, and a token/cost stats bar](docs/assets/cockpit.png)

## Quickstart

Not published to PyPI yet — install from source:

```bash
git clone https://github.com/rahulmg05/blackbox.git
cd blackbox
uv tool install .          # or: pipx install .
agentdeck install          # registers the recorder as a Claude Code hook
agentdeck                  # launch the live cockpit
```

That's it — `agentdeck install` is idempotent and additive (it merges into
`~/.claude/settings.json`, backing the file up first, and never touches
hooks it didn't add). Run `agentdeck doctor` any time to check that recording
is actually working.

## Usage

| Command                           | What it does                                       |
| --------------------------------- | -------------------------------------------------- |
| `agentdeck`                       | Launch the live cockpit (default: focused mode)    |
| `agentdeck install` / `uninstall` | Register / remove the recorder hook                |
| `agentdeck doctor`                | Check that recording is healthy                    |
| `agentdeck replay --session <id>` | Replay a past session                              |
| `agentdeck replay`                | Browse past sessions, then replay one              |
| `agentdeck export <session>`      | Export a session to a self-contained HTML timeline |

### View modes

| Mode                  | What you see                                                                                                                                                                      |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Focused** (default) | Sidebar of all sessions (name, liveness, tool/fail counts) on the left; the selected session's full timeline in the middle; a stats bar (tokens, cost, tokens/min) at the bottom. |
| **Firehose**          | Every session's events interleaved into one chronological, color-coded scrolling log — the fastest way to watch everything happening on the machine at once.                      |
| **Wall**              | A tiled grid, one pane per live session (up to 4, with a "+N more" strip beyond that) — good for keeping an eye on several sessions at a glance.                                  |
| **Replay**            | The same UI fed from a past session's log instead of live data, with speed control and seeking — watch any session like game film.                                                |

### Other things you can do

- **Install/uninstall the recorder** without hand-editing config — `agentdeck install` merges hook entries into `~/.claude/settings.json` (backing the file up first) and never touches hooks it didn't add; `agentdeck uninstall` reverses it cleanly.
- **Check recording health** any time with `agentdeck doctor` — confirms the hook is registered, the courier script runs, the log directory is writable, and reports how long ago the last event landed.
- **Drill into any event** — `enter` on a timeline row opens the full pretty-printed payload (tool input/output, prompt text, etc.).
- **Read the actual conversation** — `t` opens the chat transcript for the selected session, reconstructed from Claude Code's own transcript file.
- **Search and filter** — `/` searches the current view (event text, file paths, commands); `e` shows errors only; number keys filter the firehose to a single session.
- **Track spend** — per-turn and per-session token/cost estimates, backed by an editable pricing table in `~/.agentdeck/config.toml`.
- **Get notified** — optional desktop notifications on long-running tool completion or `Notification` events, config-gated in `config.toml`.
- **Export a session** — `agentdeck export <session>` produces a single self-contained HTML timeline you can send to someone without them installing anything.
- **Jump around fast** — `ctrl+k` opens a command palette to jump to a session, filter by event type, or change theme, without memorizing every key.
- **Toggle light/dark theme** — `d`, for whichever terminal background you're on.

### Keybindings

| Key             | Action                                                                          |
| --------------- | ------------------------------------------------------------------------------- |
| `s` / `f` / `w` | Switch mode: focused / firehose / wall                                          |
| `tab`           | Cycle the selected session (focused mode)                                       |
| `g`             | Toggle focus-follow (auto-jump to the most recently active session)             |
| `enter`         | Open the detail view for the selected row (focused mode)                        |
| `t`             | Open the chat transcript for the selected session                               |
| `/`             | Search the current view                                                         |
| `e`             | Errors-only filter                                                              |
| `d`             | Toggle dark/light theme                                                         |
| `ctrl+k`        | Command palette (jump to session, filter by event type, full theme picker, ...) |
| `p`             | Pause/resume the live view                                                      |
| `1`-`9` / `0`   | Filter the firehose to one session / clear the filter                           |
| `end`           | Resume auto-scroll after scrolling up                                           |
| `space`         | Pause/resume replay (replay mode only)                                          |
| `←` / `→`       | Seek back/forward (replay mode only)                                            |
| `]` / `[`       | Replay speed up/down: 1x → 5x → 20x → max                                       |
| `q`             | Quit                                                                            |

## How it works

A tiny stdlib-only script (`courier/emit.py`) is registered with Claude
Code's hooks system. Every lifecycle event — prompt submitted, tool about to
run, tool finished, session ended, subagent spawned, ... — gets appended as
one JSON line to `~/.agentdeck/sessions/<session_id>/main.jsonl` (or
`agent-<agent_id>.jsonl` for a subagent). The console tails that directory
tree and renders the same data live; replay just reads it from the start
instead.

See `blackbox-design-doc.md` for the full design rationale, including why
recording is file-per-actor rather than one shared log, how concurrent
writes stay safe, and how tool-call pairing handles the async hook model.
(That file predates the agentdeck rename and hasn't been updated to match —
the architecture it describes is unchanged, only the names are stale.)

## Development

```bash
uv sync --group dev
uv run agentdeck --version
uv run pytest
uv run ruff check .
```

Config (pricing table, desktop notifications) lives in
`~/.agentdeck/config.toml`, created with sensible defaults on first run of
the console — edit it directly.

## License

[MIT](LICENSE) — free to use, modify, and distribute, including
commercially. Contributions are welcome via issues and pull requests.

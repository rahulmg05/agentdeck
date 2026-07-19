"""Single source of truth for on-disk locations under ~/.agentdeck.

courier/emit.py intentionally does NOT import this — it must stay
importable standalone with zero dependency on the agentdeck package (it
has to run even if only the raw script was copied somewhere, without the
package installed). It keeps its own local copy of these same constants.
"""

import shutil
import sys
from pathlib import Path

DATA_DIR = Path.home() / ".agentdeck"
SESSIONS_DIR = DATA_DIR / "sessions"
CONFIG_PATH = DATA_DIR / "config.toml"

_LEGACY_DATA_DIR = Path.home() / ".blackbox"


def migrate_legacy_data() -> bool:
    """One-time, idempotent ~/.blackbox -> ~/.agentdeck migration.

    No-op if there's no legacy dir. Merges rather than assuming DATA_DIR
    is empty: the standalone courier (which doesn't import this module,
    by design) can independently create SESSIONS_DIR/a session file the
    moment Claude Code fires a hook, which can happen before this ever
    runs — so "DATA_DIR already exists" does not mean "nothing to
    migrate." Never raises — a migration failure must not block the CLI
    from running.
    """
    if not _LEGACY_DATA_DIR.exists():
        return False

    if not DATA_DIR.exists():
        try:
            _LEGACY_DATA_DIR.rename(DATA_DIR)
        except OSError:
            try:
                shutil.move(str(_LEGACY_DATA_DIR), str(DATA_DIR))
            except OSError as exc:
                print(
                    f"agentdeck: could not migrate {_LEGACY_DATA_DIR} to {DATA_DIR}: {exc}\n"
                    f"agentdeck: your old data is still at {_LEGACY_DATA_DIR} — move it manually.",
                    file=sys.stderr,
                )
                return False
        print(f"agentdeck: migrated {_LEGACY_DATA_DIR} -> {DATA_DIR}", file=sys.stderr)
        return True

    # DATA_DIR already has something in it (e.g. the courier started
    # writing fresh events there before this ever ran) — merge instead
    # of clobbering, only moving what doesn't already exist at the target.
    migrated_any = False

    legacy_config = _LEGACY_DATA_DIR / "config.toml"
    new_config = DATA_DIR / "config.toml"
    if legacy_config.exists() and not new_config.exists():
        try:
            shutil.move(str(legacy_config), str(new_config))
            migrated_any = True
        except OSError as exc:
            print(f"agentdeck: could not migrate {legacy_config}: {exc}", file=sys.stderr)

    legacy_sessions = _LEGACY_DATA_DIR / "sessions"
    if legacy_sessions.exists():
        new_sessions = DATA_DIR / "sessions"
        new_sessions.mkdir(parents=True, exist_ok=True)
        for entry in legacy_sessions.iterdir():
            target = new_sessions / entry.name
            if target.exists():
                continue
            try:
                shutil.move(str(entry), str(target))
                migrated_any = True
            except OSError as exc:
                print(f"agentdeck: could not migrate {entry}: {exc}", file=sys.stderr)

    try:
        if legacy_sessions.exists() and not any(legacy_sessions.iterdir()):
            legacy_sessions.rmdir()
        if _LEGACY_DATA_DIR.exists() and not any(_LEGACY_DATA_DIR.iterdir()):
            _LEGACY_DATA_DIR.rmdir()
    except OSError:
        pass

    if migrated_any:
        print(f"agentdeck: merged remaining data from {_LEGACY_DATA_DIR} into {DATA_DIR}", file=sys.stderr)
    return migrated_any

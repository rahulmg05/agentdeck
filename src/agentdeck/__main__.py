"""CLI entry point: agentdeck run | install | uninstall | doctor | replay | export"""

import argparse
import sys

from agentdeck import __version__
from agentdeck.paths import migrate_legacy_data


def main() -> None:
    migrate_legacy_data()

    parser = argparse.ArgumentParser(prog="agentdeck")
    parser.add_argument("--version", action="store_true", help="print version and exit")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="launch the live cockpit (default)")
    subparsers.add_parser("install", help="register the courier hooks in ~/.claude/settings.json")
    subparsers.add_parser("uninstall", help="remove the courier hooks")
    subparsers.add_parser("doctor", help="check recording health")

    replay_parser = subparsers.add_parser("replay", help="replay a past session")
    replay_parser.add_argument("--session", help="session id to replay")
    replay_parser.add_argument("--file", help="session file to replay")

    export_parser = subparsers.add_parser("export", help="export a session to HTML")
    export_parser.add_argument("session", help="session id to export")

    args = parser.parse_args()

    if args.version:
        print(f"agentdeck {__version__}")
        return

    if args.command in (None, "run"):
        from agentdeck.ui.app import run_app

        run_app()
    elif args.command == "install":
        from agentdeck.installer import install

        install()
    elif args.command == "uninstall":
        from agentdeck.installer import uninstall

        uninstall()
    elif args.command == "doctor":
        from agentdeck.doctor import run_doctor

        sys.exit(run_doctor())
    elif args.command == "replay":
        from agentdeck.ui.app import run_app

        run_app(
            replay_session=args.session,
            replay_file=args.file,
            replay_browse=not args.session and not args.file,
        )
    elif args.command == "export":
        from agentdeck.export import export_session

        output_path = export_session(args.session)
        print(f"agentdeck: exported to {output_path}")


if __name__ == "__main__":
    main()

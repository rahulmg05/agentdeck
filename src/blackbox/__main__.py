"""CLI entry point: blackbox run | install | uninstall | doctor | replay | export"""

import argparse
import sys

from blackbox import __version__


def main() -> None:
    parser = argparse.ArgumentParser(prog="blackbox")
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
        print(f"blackbox {__version__}")
        return

    if args.command in (None, "run"):
        from blackbox.ui.app import run_app

        run_app()
    elif args.command == "install":
        from blackbox.installer import install

        install()
    elif args.command == "uninstall":
        from blackbox.installer import uninstall

        uninstall()
    elif args.command == "doctor":
        from blackbox.doctor import run_doctor

        sys.exit(run_doctor())
    elif args.command == "replay":
        from blackbox.ui.app import run_app

        run_app(
            replay_session=args.session,
            replay_file=args.file,
            replay_browse=not args.session and not args.file,
        )
    elif args.command == "export":
        from blackbox.export import export_session

        output_path = export_session(args.session)
        print(f"blackbox: exported to {output_path}")


if __name__ == "__main__":
    main()

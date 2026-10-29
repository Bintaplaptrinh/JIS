import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from .client import request
from .paths import prepare_state, private_file


def start():
    try:
        request({"op": "stats"}, timeout=.2)
        return
    except (OSError, ConnectionError):
        pass
    state = prepare_state()
    with private_file(state / "daemon.log") as log:
        if os.fstat(log.fileno()).st_size > 1048576:
            os.ftruncate(log.fileno(), 0)
        command = [sys.executable, "-m", "jis", "daemon"]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=log, start_new_session=True)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            request({"op": "ping"}, timeout=.1)
            return
        except (OSError, ConnectionError):
            if process.poll() not in (None, 0):
                break
            time.sleep(.025)
    raise RuntimeError(f"Daemon did not start; inspect {state / 'daemon.log'}")


def main():
    parser = argparse.ArgumentParser(
        prog="jis", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""JIS is a local command assistant for interactive zsh.
It suggests successful commands from history and checks simple commands for typos.
Suggestions are filled into the prompt for review; they are never executed automatically.""",
        epilog="""Shell controls (after sourcing shell/jis.plugin.zsh):
  Up/Down       Select a history suggestion when the table is visible
  Ctrl-Space    Fill the selected suggestion; press Enter to execute
  Enter         Check for a typo before executing
  yes/no        Accept a correction for review / restore the original command
  Ctrl-G        Dismiss a suggestion or cancel a correction
  Ctrl-X Enter  Run the current command without typo correction
  jis-table-on / jis-table-off  Show / hide the suggestion table in this shell
  jis-on / jis-off              Enable / disable JIS in this shell
  jis-refresh / jis-status      Reconnect / show daemon status

Configuration: JIS_PYTHON selects Python, JIS_STATE_DIR selects the local
state directory, and JIS_SUGGEST_TABLE=0 disables the table at startup.
The daemon stores command history locally and suggests successful commands; leading-space and
HISTORY_IGNORE commands are excluded. See README.md for privacy details.

Examples:
  jis start                 Start the local daemon
  jis suggest 'git sta'     Query suggestions as JSON
  jis correct 'gti status'  Query typo corrections as JSON
  jis status                Show daemon and history statistics
  jis stop                  Stop the shared daemon""")
    parser.add_argument("--usage", action="help", help="show this detailed help and exit")
    sub = parser.add_subparsers(dest="action", required=True)
    for name, help_text in (("start", "start the shared daemon"), ("daemon", "run the daemon in the foreground"),
                            ("stop", "stop the shared daemon"), ("status", "show daemon statistics")):
        sub.add_parser(name, help=help_text, description=help_text.capitalize())
    for name in ("suggest", "correct", "record"):
        p = sub.add_parser(name, help={"suggest": "find suggestions", "correct": "find typo corrections", "record": "record a command"}[name])
        p.add_argument("buffer", help="command line to process")
        p.add_argument("--cwd", default=os.getcwd(), help="working directory (default: current directory)")
        p.add_argument("--session", default=os.environ.get("JIS_SESSION", "cli"), help="history session identifier")
        p.add_argument("--previous", default="", help="previous successful command")
        p.add_argument("--known", action="append", default=[], help="known shell command; may be repeated")
        if name == "record":
            p.add_argument("--exit-code", type=int, default=0, help="command exit status (default: 0)")
    sub.add_parser("shell", help="Print source line for current shell")
    args = parser.parse_args()
    try:
        if args.action == "daemon":
            from .daemon import main as daemon_main
            daemon_main()
        elif args.action == "start":
            start()
            print(json.dumps(request({"op": "stats"}), indent=2))
        elif args.action == "shell":
            import shlex
            plugin = Path(__file__).resolve().parents[2] / "shell/jis.plugin.zsh"
            print(f"source {shlex.quote(str(plugin))}")
        else:
            payload = {"op": {"status": "stats", "stop": "stop"}.get(args.action, args.action)}
            if hasattr(args, "buffer"):
                payload.update(buffer=args.buffer, cwd=args.cwd, session=args.session,
                               previous=args.previous, path=os.environ.get("PATH", ""),
                               known=args.known, status=getattr(args, "exit_code", 0))
            print(json.dumps(request(payload), indent=2, ensure_ascii=False))
    except (OSError, ConnectionError, RuntimeError, ValueError) as error:
        print(f"JIS: {error}", file=sys.stderr)
        sys.exit(1)

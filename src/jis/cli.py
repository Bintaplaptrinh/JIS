import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from . import __version__
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
    parser = argparse.ArgumentParser(prog="jis", description="JIS local zsh suggestion engine")
    parser.add_argument("--version", action="version", version=f"JIS {__version__}")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("start", "daemon", "stop", "status"):
        sub.add_parser(name)
    for name in ("suggest", "correct", "record"):
        p = sub.add_parser(name)
        p.add_argument("buffer")
        p.add_argument("--cwd", default=os.getcwd())
        p.add_argument("--session", default=os.environ.get("JIS_SESSION", "cli"))
        p.add_argument("--previous", default="")
        p.add_argument("--known", action="append", default=[])
        if name == "record":
            p.add_argument("--exit-code", type=int, default=0)
    sub.add_parser("shell", help="Print zsh initialization code")
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
            plugin = Path(__file__).resolve().with_name("jis.plugin.zsh")
            print(f"export JIS_PYTHON={shlex.quote(sys.executable)}")
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

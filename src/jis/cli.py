import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from .client import request
from .paths import prepare_state, private_file


def start(checkpoint=None, device="auto", threads=2, mode="assist", idle=120):
    try:
        status = request({"op": "stats"}, timeout=.2)
        if checkpoint and (status.get("model_checkpoint") != str(Path(checkpoint).resolve()) or status.get("model_preferred_device") != device or status.get("model_threads") != threads or status.get("model_mode") != mode or status.get("model_idle_seconds") != idle):
            raise RuntimeError("A different JIS configuration is already running; stop it or use another JIS_STATE_DIR")
        return
    except (OSError, ConnectionError):
        pass
    state = prepare_state()
    with private_file(state / "daemon.log") as log:
        if os.fstat(log.fileno()).st_size > 1048576:
            os.ftruncate(log.fileno(), 0)
        command = [sys.executable, "-m", "jis", "daemon"]
        if checkpoint:
            command += ["--laya-checkpoint", checkpoint, "--laya-device", device, "--laya-threads", str(threads), "--laya-mode", mode, "--laya-idle", str(idle)]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=log, start_new_session=True)
    deadline = time.monotonic() + (30 if checkpoint else 3)
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
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("start", "daemon"):
        p = sub.add_parser(name)
        p.add_argument("--laya-checkpoint", help="Optional LOCAL Laya checkpoint; lazy resource-aware process")
        p.add_argument("--laya-device", choices=("auto", "cpu", "cuda"), default="auto")
        p.add_argument("--laya-threads", type=int, choices=range(1, 9), default=2)
        p.add_argument("--laya-mode", choices=("assist", "shadow"), default="assist")
        p.add_argument("--laya-idle", type=int, default=120, help="Release model after idle seconds (>=5)")
    for name in ("stop", "status"):
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
    sub.add_parser("shell", help="Print source line for current shell")
    args = parser.parse_args()
    if hasattr(args, "laya_idle") and args.laya_idle < 5:
        parser.error("--laya-idle must be >=5 seconds")
    try:
        if args.action == "daemon":
            from .daemon import main as daemon_main
            daemon_main(args.laya_checkpoint, args.laya_device, args.laya_threads, args.laya_mode, args.laya_idle)
        elif args.action == "start":
            start(args.laya_checkpoint, args.laya_device, args.laya_threads, args.laya_mode, args.laya_idle)
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

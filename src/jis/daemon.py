import asyncio
import fcntl
import os
import signal
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from .engine import Engine
from .paths import prepare_state, private_file
from .protocol import MAX_FRAME, decode_frame, encode_response, validate
from .store import HistoryStore
from .types import Context


class Server:
    def __init__(self, store, engine, model=None):
        self.store, self.engine, self.model = store, engine, model
        self.stop = asyncio.Event()
        self.clients = 0
        self.requests = 0
        self.started = time.monotonic()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jis-engine")
        self.pending = 0

    def context(self, request, known):
        return Context(request.get("session", "cli"), request.get("cwd", os.getcwd()),
                       request.get("buffer", ""), request.get("previous", ""),
                       request.get("path", ""), known)

    async def handle(self, request, known):
        loop = asyncio.get_running_loop()
        # Control traffic must stay available during expensive inference.
        if request["op"] in {"hello", "ping", "stats", "stop"}:
            return self.dispatch(request, known)
        if request["op"] != "correct" or not self.model:
            return await loop.run_in_executor(self.worker, self.dispatch, request, known)
        context = self.context(request, known)
        candidates = await loop.run_in_executor(self.worker, self.engine.generate, context, True)
        ranked = self.engine.fast_ranker.rank(context, candidates)
        ranked = await self.model.rank(context, ranked)
        return self.engine.decide(ranked).json()

    def dispatch(self, request, known):
        op = request["op"]
        context = self.context(request, known)
        if op in {"suggest", "correct"}:
            return self.engine.suggest(context, correction_only=op == "correct").json()
        if op == "record":
            recorded = self.store.record(context.session, context.cwd, context.buffer,
                                         context.previous, request.get("status", 0))
            return {"kind": "ok" if recorded else "ignored", "recorded": recorded}
        if op == "stats":
            return {"kind": "ok", "pid": os.getpid(), "clients": self.clients,
                    "requests": self.requests, "observations": self.store.count,
                    "uptime_seconds": round(time.monotonic() - self.started, 2),
                    "ranker": "LayaAdaptive" if self.model else "HeuristicRanker",
                    "worker_threads": 1,
                    **(self.model.stats() if self.model else {"model_status": "disabled", "model_pid": None}),
                    "max_clients": 128, "max_history": self.store.limit}
        return {"kind": "ok"}

    async def client(self, reader, writer):
        if self.clients >= 128:
            writer.close()
            return
        # Linux peer credentials: only this Unix user may query history or stop.
        peer = writer.get_extra_info("socket")
        if hasattr(socket, "SO_PEERCRED"):
            _, uid, _ = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != os.getuid():
                writer.close()
                return
        self.clients += 1
        known = ()
        shell = False
        try:
            while not self.stop.is_set():
                data = await asyncio.wait_for(reader.readline(), timeout=1800)
                if not data:
                    break
                if len(data) > MAX_FRAME or not data.endswith(b"\n"):
                    break
                request = {}
                try:
                    request, shell = decode_frame(data)
                    validate(request)
                    if request["op"] == "hello":
                        known = tuple(request.get("known", []))
                    elif request.get("known"):
                        known = tuple(request["known"])
                    if self.pending >= 128:
                        response = {"kind": "none", "reason": "Busy: abstain"}
                    else:
                        self.pending += 1
                        try:
                            response = await self.handle(request, known)
                        finally:
                            self.pending -= 1
                    self.requests += 1
                    response["id"] = request.get("id", "0")
                    writer.write(encode_response(response, shell))
                    await asyncio.wait_for(writer.drain(), timeout=.5)
                    if request["op"] == "stop":
                        self.stop.set()
                        break
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    writer.write(encode_response({"id": "0", "kind": "none", "reason": "Invalid request"}, shell))
                    await asyncio.wait_for(writer.drain(), timeout=.5)
        except (OSError, asyncio.TimeoutError, ValueError):
            pass
        finally:
            self.clients -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


async def serve(checkpoint=None, device="auto", threads=2, mode="assist", idle=120):
    state = prepare_state()
    with private_file(state / "daemon.lock") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        sock = state / "jis.sock"
        if sock.exists() or sock.is_symlink():
            import stat
            info = sock.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError("Refusing to replace a non-socket state path")
            sock.unlink()
        store = HistoryStore(state / "history.sqlite3")
        model = None
        if checkpoint:
            from .model_runtime import AdaptiveModel
            from .resources import ResourcePolicy
            model = AdaptiveModel(checkpoint, state, device, threads, mode, ResourcePolicy(idle_seconds=idle))
        server = Server(store, Engine(store), model)
        loop = asyncio.get_running_loop()
        if model:
            model.start()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, server.stop.set)
        try:
            listener = await asyncio.start_unix_server(server.client, path=str(sock), limit=MAX_FRAME)
            sock.chmod(0o600)
            async with listener:
                await server.stop.wait()
        finally:
            if model:
                await model.close()
            server.worker.shutdown(wait=True, cancel_futures=True)
            store.close()
            sock.unlink(missing_ok=True)


def main(checkpoint=None, device="auto", threads=2, mode="assist", idle=120):
    asyncio.run(serve(checkpoint, device, threads, mode, idle))

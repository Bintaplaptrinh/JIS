"""Reproducible daemon-only benchmark, isolated from real shell history."""
import argparse
import concurrent.futures
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jis.store import HistoryStore


class Connection:
    def __init__(self, state):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(3)
        self.sock.connect(str(state / "jis.sock"))
        self.stream = self.sock.makefile("rb")

    def query(self, payload):
        self.sock.sendall((json.dumps(payload) + "\n").encode())
        return json.loads(self.stream.readline())

    def close(self):
        self.stream.close()
        self.sock.close()


def usage(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().split()
    status = Path(f"/proc/{pid}/status").read_text().splitlines()
    rss = int(next(line.split()[1] for line in status if line.startswith("VmRSS:")))
    return {"rss_kib": rss, "cpu_seconds": (int(fields[13]) + int(fields[14])) / os.sysconf("SC_CLK_TCK")}


def percentiles(samples):
    samples = sorted(samples)
    return {"p50_ms": round(samples[len(samples)//2], 3),
            "p95_ms": round(samples[min(len(samples)-1, int(len(samples)*.95))], 3),
            "max_ms": round(max(samples), 3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "docs/benchmark.json"))
    args = parser.parse_args()
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "cpu": next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")), "unknown"),
              "ranker": "HeuristicRanker", "history_rows": 6000,
              "scope": "Daemon RSS/CPU and socket RPC latency; excludes zsh and terminal emulator; synthetic history; no model"}
    with tempfile.TemporaryDirectory(prefix="jis-bench-") as directory:
        state = Path(directory)
        store = HistoryStore(state / "history.sqlite3")
        for i in range(6000):
            session = f"s{i % 16}"
            store.record(session, f"/task/{i % 16}", f"echo task_{i % 16}_command_{i % 128}", "git status")
        store.close()
        env = {**os.environ, "JIS_STATE_DIR": directory, "PYTHONPATH": str(ROOT / "src")}
        with (state / "log").open("w+") as log:
            daemon = subprocess.Popen([sys.executable, "-m", "jis", "daemon"], env=env, stdout=log, stderr=log)
            connections = []
            try:
                for _ in range(120):
                    if (state / "jis.sock").exists():
                        break
                    if daemon.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    time.sleep(.025)
                report["idle_connections"] = []
                for count in (1, 16, 64):
                    while len(connections) < count:
                        connection = Connection(state)
                        connection.query({"op": "ping"})
                        connections.append(connection)
                    time.sleep(.1)
                    report["idle_connections"].append({"connections": count, **usage(daemon.pid)})
                before = usage(daemon.pid)
                time.sleep(1)
                report["idle_cpu_seconds_over_1s"] = round(usage(daemon.pid)["cpu_seconds"] - before["cpu_seconds"], 4)
                context = {"op": "suggest", "session": "s0", "cwd": "/task/0", "buffer": "echo task_0_", "previous": "git status", "path": os.environ["PATH"]}
                start = time.perf_counter()
                result = connections[0].query(context)
                report["cold_completion_ms"] = round((time.perf_counter() - start)*1000, 3)
                assert result["kind"] == "completion", result
                for name, payload in (("warm_completion", context), ("warm_correction", {**context, "op": "correct", "buffer": "gti status"})):
                    samples = []
                    connections[0].query(payload)
                    for _ in range(150):
                        start = time.perf_counter()
                        connections[0].query(payload)
                        samples.append((time.perf_counter()-start)*1000)
                    report[name] = {"requests": len(samples), **percentiles(samples)}
                def workload(index):
                    payload = {**context, "session": f"s{index}", "cwd": f"/task/{index}", "buffer": f"echo task_{index}_"}
                    samples = []
                    for _ in range(40):
                        start = time.perf_counter()
                        result = connections[index].query(payload)
                        assert result["command"].startswith(payload["buffer"]), result
                        samples.append((time.perf_counter()-start)*1000)
                    return samples
                with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
                    batches = list(executor.map(workload, range(16)))
                report["concurrent_16_clients"] = {"requests": 640, **percentiles([s for batch in batches for s in batch])}
                report["after_load"] = usage(daemon.pid)
            finally:
                for connection in connections:
                    connection.close()
                daemon.terminate()
                daemon.wait(timeout=5)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

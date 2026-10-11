"""Actual offline checkpoints: pinned physical-core CPU matrix, CUDA, and cases."""
import argparse
import json
import os
from pathlib import Path
import select
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from jis.engine import Engine
from jis.model_runtime import apply_answer, question
from jis.store import HistoryStore
from jis.types import Context


def memory(pid):
    lines = Path(f"/proc/{pid}/status").read_text().splitlines()
    fields = {line.split(":")[0]: int(line.split()[1]) for line in lines if line.startswith(("VmRSS:", "VmHWM:", "Threads:"))}
    return {"rss_mib": fields["VmRSS"]/1024, "peak_rss_mib": fields["VmHWM"]/1024, "threads": fields["Threads"]}


def cpu_seconds(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().split()
    return (int(fields[13])+int(fields[14]))/os.sysconf("SC_CLK_TCK")


def percentiles(samples):
    return {"p50_ms": statistics.median(samples), "p95_ms": sorted(samples)[int((len(samples)-1)*.95)], "max_ms": max(samples)}


def physical_cores():
    cores = {}
    for cpu in sorted(os.sched_getaffinity(0)):
        root = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        key = ((root/"physical_package_id").read_text().strip(), (root/"core_id").read_text().strip())
        cores.setdefault(key, cpu)
    return list(cores.values())


def run(name, device, threads, cases):
    with tempfile.TemporaryDirectory(prefix="jis-laya-measure-") as directory:
        log = (Path(directory)/"worker.log").open("w+")
        checkpoint = ROOT/"models"/("laya-"+name)
        env = {**os.environ, "PYTHONPATH": str(ROOT/"src"), "LAYA_CUDA_AMP": "fp16"}
        start = time.perf_counter()
        affinity = physical_cores()[:threads]
        process = subprocess.Popen([sys.executable, "-m", "jis.laya_worker", str(checkpoint), device, str(threads)],
                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, env=env, text=True,
                  preexec_fn=lambda: os.sched_setaffinity(0, affinity))
        def receive(timeout=90):
            if not select.select([process.stdout], [], [], timeout)[0]:
                raise TimeoutError("worker reply exceeded deadline")
            line = process.stdout.readline()
            if not line:
                log.seek(0)
                raise RuntimeError(log.read()[-5000:])
            return json.loads(line)
        serial = 0
        def infer(context, ranked):
            nonlocal serial
            serial += 1
            payload = {"id": serial, **question(context, ranked)}
            process.stdin.write(json.dumps(payload)+"\n"); process.stdin.flush()
            reply = receive(10)
            if "error" in reply:
                raise RuntimeError(reply)
            return reply
        store = HistoryStore(Path(directory)/"history.sqlite3")
        engine = Engine(store)
        try:
            greeting = receive()
            result = {"model": name, "device": device, "threads": threads, "physical_cpu_ids": affinity,
                      "parameters": greeting["parameters"], "load_and_warmup_ms": (time.perf_counter()-start)*1000}
            context = Context("test", "/tmp", "git statsu", path="/usr/bin:/bin", known=("git",))
            ranked = engine.fast_ranker.rank(context, engine.generate(context, True))
            durations = []
            before = cpu_seconds(process.pid)
            for _ in range(40):
                reply = infer(context, ranked)
                durations.append(reply["inference_ms"])
            result["warm"] = {**percentiles(durations), "requests": 40, "cpu_seconds": cpu_seconds(process.pid)-before}
            outcomes = []
            for case in cases:
                context = Context("case", "/tmp", case["input"], path="/usr/bin:/bin",
                                  known=tuple(["git", "conda", "npm", "docker", "kubectl", "pip", "python", "echo"]+case.get("known", [])))
                ranked = engine.fast_ranker.rank(context, engine.generate(context, True))
                heuristic = engine.decide(ranked).command or None
                row = {**case, "heuristic": heuristic}
                if len(ranked) >= 2:
                    reply = infer(context, ranked)
                    choice = reply["answer"]["choice"]
                    raw = None if choice == "keep" else ranked[int(choice[1:])].command
                    assisted, reason = apply_answer(reply, ranked)
                    row.update(raw=raw, raw_correct=raw==case["expected"],
                               assisted=engine.decide(assisted).command or None, reason=reason, reply=reply)
                outcomes.append(row)
            eligible = [row for row in outcomes if "raw" in row]
            result.update(memory=memory(process.pid), cases=outcomes,
                          raw_correct=sum(row["raw_correct"] for row in eligible), eligible=len(eligible),
                          assisted_correct=sum(row.get("assisted",row["heuristic"])==row["expected"] for row in outcomes))
            if device == "cuda":
                rows = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"], text=True).splitlines()
                result["vram_mib"] = next(float(row.split(",")[1]) for row in rows if int(row.split(",")[0])==process.pid)
            return result
        finally:
            store.close()
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            log.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    cases = json.loads((ROOT/"tests/decision_cases.json").read_text())
    matrix = [("base", "cpu", n) for n in ([2] if args.quick else [2,4,6,8])]+[("base", "cuda", 2), ("typed", "cpu", 2), ("typed", "cuda", 2)]
    report = {"date": "2026-10-11", "cuda_amp": "fp16", "configs": []}
    for name, device, threads in matrix:
        result = run(name, device, threads, cases)
        report["configs"].append(result)
        (ROOT/"docs/laya-benchmark.json").write_text(json.dumps(report,indent=2)+"\n")
        print(name,device,threads, "p95",round(result["warm"]["p95_ms"],2), "RSS",round(result["memory"]["rss_mib"]),
              "raw",f"{result['raw_correct']}/{result['eligible']}", "assisted",result["assisted_correct"],flush=True)


if __name__ == "__main__":
    main()

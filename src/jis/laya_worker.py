"""Private JSON-lines model worker. Terminating this process releases runtime RAM/VRAM."""
import argparse
import json
import os
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint")
    parser.add_argument("device", choices=("cpu", "cuda"))
    parser.add_argument("threads", type=int)
    args = parser.parse_args()
    try:
        os.nice(10)
    except OSError:
        pass
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                      OMP_NUM_THREADS=str(args.threads), MKL_NUM_THREADS=str(args.threads))
    os.environ.setdefault("LAYA_CUDA_AMP", "fp16")
    # The parent can die without a cooperative shutdown; do not leave a GB-sized orphan.
    if sys.platform == "linux":
        import ctypes
        import signal
        parent = os.getppid()
        if ctypes.CDLL(None).prctl(1, signal.SIGTERM) != 0 or parent == 1 or os.getppid() != parent:
            return
    transport = sys.stdout
    # Imported libraries may print progress. Only our replies use the stdout pipe.
    sys.stdout = sys.stderr
    checkpoint = Path(args.checkpoint).resolve()
    manifest = json.loads((checkpoint/"jis-manifest.json").read_text())
    if not (checkpoint/"model.safetensors").is_file() or any(checkpoint.glob("*.pt")) or any(checkpoint.glob("*.bin")):
        raise ValueError("Only local safetensors Laya checkpoints are accepted")
    import torch
    from laya import Agent
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; parent must select an admitted device")
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    agent = Agent(str(checkpoint), device=args.device, fast=False, compile=False,
                  expected_sha256={f["path"]: f["sha256"] for f in manifest["files"]})
    if str(agent.device) != args.device:
        raise RuntimeError("Unexpected implicit device fallback")
    # Warm up before declaring ready, without terminal history.
    agent.predict({"input": "git statsu"}, {"command": {"type": "choice", "instructions": "Choose the corrected shell command.", "criteria": {"c0": "git status", "c1": "git stash", "keep": "Do not correct"}}})
    transport.write(json.dumps({"kind": "ready", "device": args.device, "parameters": sum(p.numel() for p in agent.model.parameters())})+"\n")
    transport.flush()
    for line in sys.stdin:
        if len(line.encode()) > 16384:
            raise ValueError("Oversized private worker request")
        request = json.loads(line)
        started = time.perf_counter()
        try:
            result = agent.predict(request["state"], request["questions"])
            if str(agent.device) != args.device or getattr(agent, "cpu_fallback_count", 0):
                # Avoid a hidden, unbudgeted CPU model after CUDA OOM.
                raise RuntimeError("SDK device fallback occurred")
            reply = {"id": request["id"], "answer": result["answers"]["command"], "usage": result.get("usage", {}),
                     "inference_ms": (time.perf_counter()-started)*1000}
        except Exception as error:
            reply = {"id": request["id"], "error": type(error).__name__}
        transport.write(json.dumps(reply, allow_nan=False)+"\n"); transport.flush()


if __name__ == "__main__":
    main()

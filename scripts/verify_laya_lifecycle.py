"""Observe real worker unload/reload. Pressure is injected, never exhaust host RAM."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from jis.engine import Engine
from jis.model_runtime import AdaptiveModel
from jis.resources import ResourcePolicy
from jis.store import HistoryStore
from jis.types import Context
from benchmark_laya import memory


async def ready(model, timeout=90):
    deadline = time.monotonic()+timeout
    while model.state != "ready":
        if time.monotonic() > deadline:
            raise RuntimeError("Model not ready: " + str(model.stats()))
        await asyncio.sleep(.05)


async def main():
    os.environ["LAYA_CUDA_AMP"] = "fp16"
    reports=[]
    for device in ("cpu", "cuda"):
        with tempfile.TemporaryDirectory(prefix="jis-laya-lifecycle-") as directory:
            state=Path(directory); state.chmod(0o700)
            store=HistoryStore(state/"history.sqlite3")
            engine=Engine(store)
            model=AdaptiveModel(ROOT/"models/laya-base",state,device,2,policy=ResourcePolicy(cooldown_seconds=1,idle_seconds=5))
            try:
                initial=memory(os.getpid())
                context=Context("lifecycle", "/tmp", "git statsu", path="/usr/bin:/bin",known=("git",))
                ranked=engine.fast_ranker.rank(context,engine.generate(context,True))
                model.start()
                started=time.perf_counter()
                await model.rank(context,ranked)  # demand; remains fast without a loaded model
                await ready(model)
                report={"device":device,"initial_parent_memory":initial,"load_ms":(time.perf_counter()-started)*1000,
                        "loaded_parent_memory":memory(os.getpid()),"loaded_worker_memory":memory(model.process.pid),
                        "observed_resources":model.snapshot.json()}
                begin=time.perf_counter()
                await model.rank(context,ranked)
                report["first_rank_ms"]=(time.perf_counter()-begin)*1000
                if model.infer_task:
                    await model.infer_task
                await model.rank(context,ranked)
                assert model.cache_hits==1
                report["cache_hit_verified"]=True
                # Cases deliberately contain equally plausible spelling choices.
                # Expected intent is synthetic; never execute the proposed command.
                ambiguity=[]
                for case in json.loads((ROOT/"tests/laya_ambiguity_cases.json").read_text()):
                    ctx=Context("ambiguity","/tmp",case["input"],case["previous"],path="/nonexistent",known=tuple(case["known"]))
                    options=engine.fast_ranker.rank(ctx,engine.generate(ctx,True))
                    heuristic=engine.decide(options).command or None
                    await model.rank(ctx,options)
                    if model.infer_task:
                        await model.infer_task
                    assisted=await model.rank(ctx,options)
                    ambiguity.append({**case,"heuristic":heuristic,"assisted":engine.decide(assisted).command or None,"reply":model.last_result,"reason":model.reason})
                report["ambiguity_cases"]=ambiguity
                worker=model.process
                # Fault injection exercises the SAME policy branch as real low RAM.
                await model.tick(replace(model.snapshot,available_mib=100))
                assert worker.returncode is not None and not Path(f"/proc/{worker.pid}").exists()
                report["low_memory_injection_reaped_pid"]=worker.pid
                report["unloaded_parent_memory"]=memory(os.getpid())
                await asyncio.sleep(1.1)
                await model.rank(context,ranked)
                await ready(model)
                report["reload_pid"]=model.process.pid
                assert report["reload_pid"]!=worker.pid
                # Stop demand and wait for a real idle timeout (5s for this check).
                await asyncio.sleep(6)
                assert model.process is None and model.reason=="idle",model.stats()
                report["idle_release_verified"]=True
                report["stats"]=model.stats()
                reports.append(report)
                (ROOT/"docs/laya-lifecycle.json").write_text(json.dumps(reports,indent=2)+"\n")
                print(device,"PASS: actual load, cached result, pressure eviction, reload, idle release",flush=True)
            except Exception:
                log = state/"model.log"
                if log.exists():
                    print(log.read_text()[-4000:], file=sys.stderr)
                raise
            finally:
                await model.close()
                store.close()


if __name__=="__main__":
    asyncio.run(main())

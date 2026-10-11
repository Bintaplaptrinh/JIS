import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from jis.model_runtime import AdaptiveModel, apply_answer
from jis.rankers import HeuristicRanker
from jis.resources import ResourcePolicy, ResourceProbe, Snapshot
from jis.types import Candidate, Context


def candidates(close=False):
    first = Candidate("git status", "correction", "typo", {}, .8)
    second = Candidate("git stash", "correction", "typo", {}, .77 if close else .6)
    return [first, second]


class PolicyTests(unittest.TestCase):
    def test_resource_admission_and_hysteresis(self):
        policy = ResourcePolicy()
        sample = Snapshot(8000, .2, gpu_free_mib=5000, gpu_busy=10)
        self.assertEqual(policy.admit(sample, "auto"), "cuda")
        self.assertEqual(policy.admit(replace(sample, gpu_free_mib=100), "auto"), "cpu")
        self.assertIsNone(policy.admit(replace(sample, gpu_free_mib=100), "cuda"))
        for restricted in (replace(sample, available_mib=2000), replace(sample, cpu_busy=.9), replace(sample, memory_psi=3), replace(sample, valid=False)):
            self.assertIsNone(policy.admit(restricted, "auto"))
        self.assertIsNone(policy.pressure(Snapshot(2000, .8), "cpu"))
        self.assertEqual(policy.pressure(Snapshot(500, .2), "cpu"), "memory_pressure")

    def test_real_probe_without_ml_imports(self):
        self.assertTrue(ResourceProbe().sample().valid)
        self.assertNotIn("torch", sys.modules)

    def test_inherited_cgroup_memory_and_cpu_limits(self):
        probe = ResourceProbe()
        probe.cgroup = Path("/sys/fs/cgroup/jis-test/leaf")
        parent = probe.cgroup.parent
        original_read = Path.read_text
        def read(path, *args, **kwargs):
            if path == parent/"memory.max":
                return str(4096*1024**2)
            if path == parent/"memory.current":
                return str(3072*1024**2)
            if path == parent/"cpu.max":
                return "100000 100000"
            return original_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", read), patch("os.getloadavg", return_value=(2,2,2)):
            sample = probe.sample()
        self.assertTrue(sample.valid)
        self.assertLessEqual(sample.available_mib, 1024)
        self.assertEqual(sample.cpu_busy, 1)
        self.assertIsNone(ResourcePolicy().admit(sample,"auto"))

    def test_answer_only_tiebreaks_weak_evidence(self):
        reply = {"answer": {"choice": "c1", "answer_confidence": .95, "probabilities": {"c0": .03, "c1": .95, "keep": .02}}}
        strong = candidates()
        self.assertIs(apply_answer(reply, strong)[0], strong)
        weak = candidates(True)
        result, reason = apply_answer(reply, weak)
        self.assertEqual(result[0].command, "git stash")
        self.assertEqual(reason, "model_tiebreak")
        self.assertEqual(weak[0].score, .8)
        self.assertIs(apply_answer(reply, weak, "shadow")[0], weak)
        self.assertIs(apply_answer({**reply, "usage": {"truncated": True}}, weak)[0], weak)
        top_reply = {"answer": {"choice": "c0", "answer_confidence": .95, "probabilities": {"c0": .95, "c1": .03, "keep": .02}}}
        result, reason = apply_answer(top_reply, weak)
        self.assertEqual(reason, "model_tiebreak")
        self.assertEqual(result[0].score, .95)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/"model.safetensors").write_bytes(b"fixture")
        (self.root/"jis-manifest.json").write_text(json.dumps({"files": []}))
        self.model = AdaptiveModel(self.root, self.root, "cpu", policy=ResourcePolicy(stable_samples=2, cooldown_seconds=.1, idle_seconds=1))
        self.model.worker_command = [sys.executable, str(Path(__file__).with_name("fake_model_worker.py"))]
        self.context = Context("s", "/tmp", "git statsu")
        self.good = Snapshot(10000, .1)

    async def asyncTearDown(self):
        await self.model.close()
        self.tmp.cleanup()

    async def ready(self):
        await self.model.rank(self.context, candidates())
        await self.model.tick(self.good)
        self.assertEqual(self.model.state, "unloaded")
        await self.model.tick(self.good)
        await self.model.load_task
        self.assertEqual(self.model.state, "ready")

    async def test_lazy_load_memory_evict_reload_and_idle_release(self):
        self.assertIsNone(self.model.process)
        await self.ready()
        process = self.model.process
        await self.model.tick(Snapshot(100, .1))
        self.assertIsNotNone(process.returncode)
        self.assertIsNone(self.model.process)
        self.assertEqual(self.model.reason, "memory_pressure")
        await self.model.tick(self.good)
        self.assertEqual(self.model.state, "cooldown")
        await asyncio.sleep(.11)
        await self.ready()
        self.model.last_used = time.monotonic()-2
        process = self.model.process
        await self.model.tick(self.good)
        self.assertEqual(self.model.reason, "idle")
        self.assertIsNotNone(process.returncode)

    async def test_busy_deadline_and_hung_worker_reaped(self):
        with patch.dict(os.environ, JIS_TEST_INFER_SLEEP="2"):
            await self.ready()
        self.model.infer_timeout = .2
        process = self.model.process
        start = time.monotonic()
        result = await self.model.rank(self.context, candidates())
        self.assertLess(time.monotonic()-start, .15)
        self.assertEqual(result[0].command, "git status")
        self.assertTrue(self.model.busy)
        await self.model.rank(self.context, candidates())
        self.assertEqual(self.model.busy_fallbacks, 1)
        await asyncio.sleep(.3)
        self.assertIsNone(self.model.process)
        self.assertIsNotNone(process.returncode)
        self.assertEqual(self.model.calls, 1)

    async def test_pressure_during_load_releases_process(self):
        with patch.dict(os.environ, JIS_TEST_LOAD_SLEEP="2"):
            await self.model.rank(self.context, candidates())
            await self.model.tick(self.good); await self.model.tick(self.good)
            for _ in range(100):
                if self.model.process:
                    break
                await asyncio.sleep(.005)
        process = self.model.process
        self.assertIsNotNone(process)
        await self.model.tick(Snapshot(100, .1))
        self.assertIsNotNone(process.returncode)
        self.assertIsNone(self.model.process)

    async def test_cpu_spike_requires_persistent_pressure(self):
        await self.ready()
        spike = Snapshot(10000, .98)
        await self.model.tick(spike)
        self.assertEqual(self.model.state, "ready")
        await self.model.tick(self.good)
        await self.model.tick(spike); await self.model.tick(spike)
        self.assertEqual(self.model.state, "ready")
        await self.model.tick(spike)
        self.assertEqual(self.model.reason, "cpu_pressure")

    async def test_cache_binds_session_and_context(self):
        await self.ready()
        await self.model.rank(self.context, candidates())
        await self.model.rank(self.context, candidates())
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(self.model.cache_hits, 1)
        await self.model.rank(replace(self.context, session="other-terminal"), candidates())
        self.assertEqual(self.model.calls, 2)
        await self.model.rank(replace(self.context, cwd="/other"), candidates())
        self.assertEqual(self.model.calls, 3)


if __name__ == "__main__":
    unittest.main()

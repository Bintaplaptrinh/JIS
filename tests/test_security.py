import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from jis.daemon import Server
from jis.engine import Engine
from jis.paths import private_file, prepare_state
from jis.policy import learnable, risky
from jis.providers import CommandIndex, TypoProvider
from jis.protocol import validate
from jis.rankers import HeuristicRanker
from jis.model_runtime import AdaptiveModel, apply_answer
from jis.store import HistoryStore
from jis.types import Candidate, Context


class SecurityTests(unittest.TestCase):
    def test_symlink_and_hardlink_state_files_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "unrelated"
            target.write_text("must stay unchanged")
            link = root / "daemon.log"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                with private_file(link):
                    pass
            link.unlink()
            os.link(target, link)
            with self.assertRaises(RuntimeError):
                with private_file(link):
                    pass
            self.assertEqual(target.read_text(), "must stay unchanged")

    def test_symlink_db_and_sidecar_refused(self):
        for suffix in ("", "-wal", "-shm"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / "unrelated"
                target.write_text("keep")
                (root / ("history.sqlite3" + suffix)).symlink_to(target)
                with self.assertRaises(OSError):
                    HistoryStore(root / "history.sqlite3")
                self.assertEqual(target.read_text(), "keep")

    def test_state_directory_symlink_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "actual").mkdir()
            (root / "state").symlink_to(root / "actual", target_is_directory=True)
            with patch.dict(os.environ, JIS_STATE_DIR=str(root / "state")):
                with self.assertRaises(RuntimeError):
                    prepare_state()

    def test_database_permissions_and_startup_pruning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            store = HistoryStore(path, limit=10)
            for i in range(10):
                store.record("s", directory, f"echo {i}")
            store.close()
            path.chmod(0o666)
            store = HistoryStore(path, limit=3)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(store.count, 3)
            for suffix in ("-wal", "-shm"):
                self.assertEqual(Path(str(path)+suffix).stat().st_mode & 0o777, 0o600)
            store.close()

    def test_request_path_cannot_execute_fake_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "EXECUTED"
            fake = root / "git"
            fake.write_text(f"#!/bin/sh\ntouch {marker}\n")
            fake.chmod(0o700)
            store = HistoryStore(root / "history.sqlite3")
            context = Context("s", directory, "git statsu", path=directory)
            Engine(store).suggest(context, correction_only=True)
            self.assertFalse(marker.exists())
            store.close()

    def test_git_helper_output_and_exit_are_bounded(self):
        for program in ("import os; os.write(1, b'x'*40000)",
                        "import os,time; os.close(1); time.sleep(2)"):
            with self.subTest(program=program), tempfile.TemporaryDirectory() as directory:
                helper = Path(directory) / "helper"
                helper.write_text(f"#!{sys.executable}\n{program}\n")
                helper.chmod(0o700)
                index = CommandIndex()
                index.trusted_git = str(helper)
                start = time.monotonic()
                self.assertIsNone(TypoProvider(index).git_aliases(Context("s", directory, "git statsu")))
                self.assertLess(time.monotonic()-start, .3)

    def test_secret_variants_filtered(self):
        for command in (
            "curl --data '{\"api_key\":\"example\"}' https://example.com",
            "curl --data '{\"password\":\"example\"}' https://example.com",
            "curl https://user:password@example.com",
            "echo -----BEGIN RSA PRIVATE KEY-----",
            "export GITHUB_TOKEN='example'",
            "curl -H 'Authorization: Bearer example' https://example.com",
        ):
            with self.subTest(command=command):
                self.assertFalse(learnable(command))

    def test_dangerous_path_and_wrapper_bypasses(self):
        for command in (
            "/bin/rm -rf /tmp/example", "'rm' -rf /tmp/example", "command rm -rf /tmp/example",
            "env rm -rf /tmp/example", "/usr/bin/sudo true", "xargs rm", "docker system prune",
            "kubectl delete namespace demo", "mkfs.ext4 /dev/example", "/usr/bin/git push --force",
        ):
            with self.subTest(command=command):
                self.assertTrue(risky(command))

    def test_protocol_rejects_controls_surrogates_and_bool_status(self):
        for request in (
            {"op": "ping", "id": "\x1b[31m"}, {"op": "ping", "buffer": "\ud800"},
            {"op": "record", "status": True}, {"op": "hello", "known": ["bad\x00name"]},
            {"op": "hello", "known": ["\udfff"]}, {"op": "suggest", "cwd": "/tmp\nhello"},
        ):
            with self.subTest(request=request), self.assertRaises(ValueError):
                validate(request)

    def test_sql_injection_is_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.sqlite3")
            session = "'; DROP TABLE observations; --"
            store.record(session, directory, "echo public")
            rows = store.retrieve(Context(session, directory, "echo "))
            self.assertEqual(rows[0][3], "echo public")
            store.close()

    def test_pickle_only_checkpoint_refused_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "model.pt").write_bytes(b"not pickle")
            with self.assertRaises(ValueError):
                AdaptiveModel(directory, directory)

    def test_model_invalid_answers_refused(self):
        candidates = [Candidate("git status", "correction", "typo", {"similarity": .8, "common": 1, "distance": 1}),
                      Candidate("git stash", "correction", "typo", {"similarity": .6, "common": 1, "distance": 2})]
        for answer in ({}, {"choice": "c999", "answer_confidence": .99},
                       {"choice": "c0", "answer_confidence": float("nan")},
                       {"choice": "c1", "answer_confidence": True},
                       {"choice": "c0", "answer_confidence": .99, "probabilities": {"c0": 1, "c1": 1, "keep": 1}}):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                apply_answer({"answer": answer}, candidates)


class SchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_wait_does_not_block_control_traffic(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.sqlite3")
            class SlowModel:
                async def rank(self, context, candidates):
                    await asyncio.sleep(.08)
                    return candidates
            server = Server(store, Engine(store), SlowModel())
            request = {"op": "correct", "session": "s", "cwd": directory, "buffer": "git statsu", "path": "/usr/bin:/bin"}
            try:
                task = asyncio.create_task(server.handle(request, ("git",)))
                await asyncio.sleep(.02)
                start = time.monotonic()
                self.assertEqual((await server.handle({"op": "ping"}, ()))["kind"], "ok")
                self.assertLess(time.monotonic()-start, .05)
                self.assertEqual((await task)["command"], "git status")
            finally:
                server.worker.shutdown(wait=True)
                store.close()


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from pathlib import Path
from jis.engine import Engine
from jis.providers import distance
from jis.protocol import encode_field, decode_frame, encode_response, MAX_FRAME, validate
from jis.store import HistoryStore
from jis.types import Context


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.tmp.name) / "test.sqlite3", limit=100)
        self.engine = Engine(self.store)
        self.path = os.environ["PATH"]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def context(self, buffer, session="a", cwd=None, previous="", known=()):
        return Context(session, cwd or self.tmp.name, buffer, previous, self.path, known)

    def test_transposition_and_arguments_preserved(self):
        self.assertEqual(distance("gti", "git"), 1)
        result = self.engine.suggest(self.context('gti log --oneline "file with spaces"'))
        self.assertEqual(result.command, 'git log --oneline "file with spaces"')
        self.assertEqual(result.kind, "correction")

    def test_subcommand(self):
        self.assertEqual(self.engine.suggest(self.context("git statsu")).command, "git status")

    def test_valid_alias_function_not_corrected(self):
        self.assertEqual(self.engine.suggest(self.context("gti status", known=("gti",))).kind, "none")

    def test_git_alias_not_corrected(self):
        import subprocess
        subprocess.run(["git", "init", "-q", self.tmp.name], check=True)
        subprocess.run(["git", "-C", self.tmp.name, "config", "alias.statsu", "status"], check=True)
        self.assertEqual(self.engine.suggest(self.context("git statsu")).kind, "none")

    def test_complex_and_incomplete_inputs_abstain(self):
        for command in ('gti status; echo unsafe', 'gti $(touch file)', 'gti status | cat', "gti 'unfinished", ' gti status', "gti\nstatus"):
            with self.subTest(command=command):
                self.assertEqual(self.engine.suggest(self.context(command)).kind, "none")

    def test_same_directory_session_separation(self):
        for _ in range(20):
            self.store.record("b", self.tmp.name, "python task_b.py")
        self.store.record("a", self.tmp.name, "python task_a.py")
        self.assertEqual(self.engine.suggest(self.context("python t", "a")).command, "python task_a.py")
        self.assertEqual(self.engine.suggest(self.context("python t", "b")).command, "python task_b.py")

    def test_directory_and_transition(self):
        self.store.record("a", "/task/a", "git log", "git status")
        self.store.record("b", "/task/b", "git diff", "git status")
        self.assertEqual(self.engine.suggest(self.context("git ", "a", "/task/a", "git status")).command, "git log")
        self.assertEqual(self.engine.suggest(self.context("git ", "b", "/task/b", "git status")).command, "git diff")

    def test_failures_not_suggested(self):
        self.store.record("a", self.tmp.name, "python missing.py", status=2)
        self.assertEqual(self.engine.suggest(self.context("python m")).kind, "none")

    def test_privacy(self):
        for command in (" export TOKEN=abc", "curl --password abc", 'curl -H "Authorization: Bearer abc"', "export API_KEY=abc", "echo\x1b[31mhello"):
            self.assertFalse(self.store.record("a", self.tmp.name, command))
        self.store.record("a", self.tmp.name, "echo public", "export TOKEN=secret")
        self.assertEqual(self.store.db.execute("SELECT previous FROM observations").fetchone()[0], "")

    def test_dangerous_history_not_completed(self):
        for command, prefix in (("rm -rf /tmp/demo", "rm "), ("git push --force", "git p"), ("git reset --hard", "git re")):
            self.store.record("a", self.tmp.name, command)
            self.assertNotEqual(self.engine.suggest(self.context(prefix)).kind, "completion")

    def test_literal_percent_underscore_prefix(self):
        self.store.record("a", self.tmp.name, "echo a_b% done")
        self.store.record("a", self.tmp.name, "echo axbZZ wrong")
        self.assertEqual(self.engine.suggest(self.context("echo a_b%")).command, "echo a_b% done")

    def test_history_bounded(self):
        for i in range(200):
            self.store.record("a", self.tmp.name, f"echo {i}")
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM observations").fetchone()[0], 100)

    def test_relative_path_is_terminal_specific(self):
        directory = Path(self.tmp.name) / "tools"
        directory.mkdir()
        executable = directory / "customcmd"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o700)
        context = Context("a", self.tmp.name, "customcnd", path="tools")
        self.assertEqual(self.engine.suggest(context).command, "customcmd")

    def test_default_engine_does_not_import_torch(self):
        import sys
        self.assertNotIn("torch", sys.modules)


class ProtocolTests(unittest.TestCase):
    def test_shell_roundtrip_without_eval(self):
        fields = ["1", "suggest", "s", "/tmp/a\tb", "", "echo %0A `literal` $HOME", "0", "/bin", "alias\nfunction"]
        request, shell = decode_frame(("\t".join(map(encode_field, fields)) + "\n").encode())
        self.assertTrue(shell)
        self.assertEqual(request["buffer"], fields[5])
        self.assertEqual(request["cwd"], fields[3])
        self.assertEqual(request["known"], ["alias", "function"])
        with self.assertRaises(ValueError):
            validate(request)  # control characters in CWD are deliberately refused

    def test_bounds(self):
        with self.assertRaises(ValueError):
            validate({"op": "suggest", "buffer": "x" * 4097})
        with self.assertRaises(ValueError):
            validate({"op": "record", "status": -1})

    def test_response_bound_for_large_candidate_evidence(self):
        import json
        data = encode_response({"kind": "completion", "command": "echo public", "candidates": [{"command": "x" * 4096}] * 8})
        self.assertLessEqual(len(data), MAX_FRAME)
        self.assertTrue(json.loads(data)["evidence_truncated"])


if __name__ == "__main__":
    unittest.main()

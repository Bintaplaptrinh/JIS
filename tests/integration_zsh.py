"""Real zsh/ZLE tests via a pseudo-terminal. Standard library only."""
import json
import os
import pty
import re
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rpc(state, payload):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(2)
        connection.connect(str(state / "jis.sock"))
        connection.sendall((json.dumps(payload) + "\n").encode())
        with connection.makefile("rb") as stream:
            return json.loads(stream.readline())


class Terminal:
    def __init__(self, env):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe("zsh", ["zsh", "-di"], env)
        self.read_until("JIS> ")

    def send(self, text):
        os.write(self.fd, text.encode())

    def read_until(self, text, timeout=4):
        output = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if select.select([self.fd], [], [], .05)[0]:
                try:
                    chunk = os.read(self.fd, 65536)
                except OSError:
                    break
                output += re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", chunk.decode(errors="replace"))
                if text in output:
                    return output
        raise AssertionError(f"Expected {text!r}; terminal output: {output!r}")

    def drain(self):
        output = ""
        deadline = time.monotonic() + .25
        while time.monotonic() < deadline:
            if select.select([self.fd], [], [], .02)[0]:
                output += os.read(self.fd, 65536).decode(errors="replace")
        return output

    def inspect(self):
        self.send("\x14")
        return self.read_until("JIS_BUFFER:") + self.drain()

    def close(self):
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        os.close(self.fd)
        os.waitpid(self.pid, 0)


class ZshIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="jis-zsh-")
        cls.state = Path(cls.tmp.name) / "state"
        cls.env = {**os.environ, "JIS_STATE_DIR": str(cls.state), "ZDOTDIR": cls.tmp.name,
                   "JIS_PYTHON": sys.executable, "PYTHONPATH": str(ROOT / "src"), "TERM": "xterm-256color"}
        cls.log = (Path(cls.tmp.name) / "daemon.log").open("w+")
        daemon_command = [sys.executable, "-m", "jis", "daemon"]
        if os.environ.get("JIS_MODEL_TEST"):
            daemon_command += ["--laya-checkpoint", str(ROOT / "models/laya-base"),
                               "--laya-device", os.environ["JIS_MODEL_TEST"], "--laya-threads", "2"]
        cls.daemon = subprocess.Popen(daemon_command, env=cls.env,
                                      stdout=cls.log, stderr=cls.log)
        for _ in range(2400 if os.environ.get("JIS_MODEL_TEST") else 120):
            if (cls.state / "jis.sock").exists():
                break
            if cls.daemon.poll() is not None:
                cls.log.seek(0)
                raise RuntimeError(cls.log.read())
            time.sleep(.025)
        if os.environ.get("JIS_MODEL_TEST"):
            payload = {"op": "correct", "session": "warmup", "cwd": "/tmp", "buffer": "git statsu", "path": "/usr/bin:/bin", "known": ["git"]}
            rpc(cls.state, payload)
            deadline = time.monotonic()+90
            while rpc(cls.state, {"op": "stats"})["model_status"] != "ready":
                if time.monotonic() > deadline:
                    cls.log.seek(0)
                    raise RuntimeError("Laya not ready: " + str(rpc(cls.state, {"op": "stats"})) + cls.log.read())
                time.sleep(.1)
        rc = """PROMPT='JIS> '
RPROMPT=''
setopt no_beep
%s
source %s/shell/jis.plugin.zsh
_jis_inspect() { print -r -- "JIS_BUFFER:$BUFFER"; zle -R; }
zle -N jis-inspect _jis_inspect
bindkey '^T' jis-inspect
"""
        cls.rc_template = rc
        (Path(cls.tmp.name) / ".zshrc").write_text(rc % ("", ROOT))

    @classmethod
    def tearDownClass(cls):
        cls.daemon.terminate()
        cls.daemon.wait(timeout=5)
        cls.log.close()
        cls.tmp.cleanup()

    def setUp(self):
        self.terminal = Terminal(self.env)

    def tearDown(self):
        self.terminal.close()

    def test_yes_fills_without_execution(self):
        t = self.terminal
        t.send("ehco JIS_EXECUTION_SENTINEL\r")
        t.read_until("Do you mean echo JIS_EXECUTION_SENTINEL")
        t.send("yes\r")
        filled = t.read_until("filled only") + t.drain()
        self.assertNotIn("\r\nJIS_EXECUTION_SENTINEL\r\n", filled)
        self.assertIn("JIS_BUFFER:echo JIS_EXECUTION_SENTINEL", t.inspect())
        t.send("\r")
        executed = t.read_until("\r\nJIS_EXECUTION_SENTINEL\r\n")
        self.assertIn("JIS_EXECUTION_SENTINEL", executed)

    def test_no_and_cancel_preserve_original(self):
        t = self.terminal
        t.send("gti status\r")
        t.read_until("Do you mean git status")
        t.send("no\r")
        t.read_until("original command restored")
        self.assertIn("JIS_BUFFER:gti status", t.inspect())
        t.send("\r")
        t.read_until("Do you mean git status")
        t.send("\x07")
        t.read_until("suggestion dismissed")
        self.assertIn("JIS_BUFFER:gti status", t.inspect())

    def test_dynamic_alias_not_corrected(self):
        t = self.terminal
        t.send("alias gti='echo JIS_ALIAS_OK'\r")
        t.read_until("JIS> ")
        t.drain()
        t.send("gti status\r")
        t.read_until("\r\nJIS_ALIAS_OK status\r\n")

    def test_completion_fill_only(self):
        t = self.terminal
        t.send("echo JIS_HISTORY_SENTINEL\r")
        t.read_until("\r\nJIS_HISTORY_SENTINEL\r\n")
        t.drain()
        t.send("echo JIS_HI")
        t.drain()
        t.send("\x00")  # Ctrl-Space
        t.drain()
        self.assertIn("JIS_BUFFER:echo JIS_HISTORY_SENTINEL", t.inspect())

    def test_complex_command_not_corrected(self):
        t = self.terminal
        t.send("gti status; echo JIS_COMPLEX_PASSTHROUGH\r")
        output = t.read_until("\r\nJIS_COMPLEX_PASSTHROUGH\r\n")
        self.assertNotIn("Do you mean", output)

    def test_ignored_commands_not_learned(self):
        t = self.terminal
        t.send(" echo JIS_PRIVATE_SPACE\r")
        t.read_until("\r\nJIS_PRIVATE_SPACE\r\n")
        t.drain()
        t.send("HISTORY_IGNORE='*JIS_PRIVATE_GLOB*'\r")
        t.read_until("JIS> ")
        t.drain()
        t.send("echo JIS_PRIVATE_GLOB\r")
        t.read_until("\r\nJIS_PRIVATE_GLOB\r\n")
        t.drain()
        for prefix in ("echo JIS_PRIVATE_SPACE", "echo JIS_PRIVATE_GLOB"):
            result = rpc(self.state, {"op": "suggest", "buffer": prefix[:-1], "cwd": str(ROOT), "path": os.environ["PATH"]})
            self.assertEqual(result["kind"], "none", result)

    def test_bypass_does_not_correct(self):
        t = self.terminal
        t.send("gti status\x18\r")
        output = t.read_until("command not found: gti")
        self.assertNotIn("Do you mean", output)

    def test_many_clients_share_one_daemon(self):
        clients = []
        try:
            pid = rpc(self.state, {"op": "stats"})["pid"]
            for _ in range(32):
                connection = socket.socket(socket.AF_UNIX)
                connection.connect(str(self.state / "jis.sock"))
                connection.sendall(b'{"op":"ping"}\n')
                connection.recv(1024)
                clients.append(connection)
            status = rpc(self.state, {"op": "stats"})
            self.assertEqual(status["pid"], pid)
            self.assertEqual(status["worker_threads"], 1)
            self.assertGreaterEqual(status["clients"], 32)
        finally:
            for connection in clients:
                connection.close()

    def test_malformed_client_does_not_break_daemon(self):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(1)
            connection.connect(str(self.state / "jis.sock"))
            connection.sendall(b'{bad json}\n')
            self.assertEqual(json.loads(connection.recv(1024))["kind"], "none")
        self.assertEqual(rpc(self.state, {"op": "ping"})["kind"], "ok")

    def test_deep_json_surrogates_and_oversize_disconnect(self):
        for payload in (b'{"op":"ping","id":"\\ud800"}\n', b'{"op":"ping","extra":' + b'['*1500 + b'0' + b']'*1500 + b'}\n'):
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(1)
                connection.connect(str(self.state / "jis.sock"))
                connection.sendall(payload)
                self.assertEqual(json.loads(connection.recv(1024))["kind"], "none")
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(1)
            connection.connect(str(self.state / "jis.sock"))
            connection.sendall(b'x'*40000 + b'\n')
            try:
                self.assertEqual(connection.recv(1024), b'')
            except ConnectionResetError:
                pass
        self.assertEqual(rpc(self.state, {"op": "ping"})["kind"], "ok")

    def test_history_ignore_bypasses_correction(self):
        t = self.terminal
        t.send("HISTORY_IGNORE='gti JIS_IGNORED*'\r")
        t.read_until("JIS> ")
        t.drain()
        t.send("gti JIS_IGNORED\r")
        output = t.read_until("command not found: gti")
        self.assertNotIn("Do you mean", output)

    def test_shell_rejects_malformed_response(self):
        t = self.terminal
        t.send("_jis_parse $'=1\\t=correction\\t=bad%0Acommand\\t=reason'; print JIS_PARSE_EXIT:$?\r")
        t.read_until("JIS_PARSE_EXIT:1")

    @unittest.skipUnless(os.environ.get("JIS_MODEL_TEST"), "requires real model profile")
    def test_long_input_bypasses_model_and_model_recovers(self):
        deadline = time.monotonic()+5
        while rpc(self.state, {"op": "stats"})["model_busy"]:
            if time.monotonic() > deadline:
                self.fail("previous model call stuck")
            time.sleep(.025)
        before = rpc(self.state, {"op": "stats"})["model_calls"]
        payload = {"op": "correct", "session": "long-case", "cwd": str(ROOT), "buffer": "git statsu -- " + "word "*600,
                   "path": "/usr/bin:/bin", "known": ["git"]}
        result = rpc(self.state, payload)
        self.assertEqual(result["kind"], "correction")
        self.assertEqual(rpc(self.state, {"op": "stats"})["model_calls"], before)
        result = rpc(self.state, {**payload, "buffer": "git statsu"})
        self.assertEqual(result["command"], "git status")
        deadline = time.monotonic()+5
        while rpc(self.state, {"op": "stats"})["model_busy"]:
            if time.monotonic() > deadline:
                self.fail("Laya request stuck")
            time.sleep(.025)
        self.assertGreater(rpc(self.state, {"op": "stats"})["model_calls"], before)

    def test_two_terminals_are_independent(self):
        a = self.terminal
        b = Terminal(self.env)
        try:
            a.send("echo JIS_TASK_A\r")
            a.read_until("\r\nJIS_TASK_A\r\n")
            a.drain()
            b.send("echo JIS_TASK_B\r")
            b.read_until("\r\nJIS_TASK_B\r\n")
            b.drain()
            for terminal, expected in ((a, "A"), (b, "B")):
                terminal.send("echo JIS_TASK_")
                terminal.drain()
                terminal.send("\x00")
                terminal.drain()
                self.assertIn(f"JIS_BUFFER:echo JIS_TASK_{expected}", terminal.inspect())
        finally:
            b.close()

    def test_existing_autosuggestions(self):
        t = self.terminal
        t.close()
        rc = Path(self.tmp.name) / ".zshrc"
        rc.write_text(self.rc_template % ("source /usr/share/zsh-autosuggestions/zsh-autosuggestions.zsh", ROOT))
        try:
            self.terminal = Terminal(self.env)
            self.terminal.send("gti status\r")
            self.terminal.read_until("Do you mean git status")
            self.terminal.send("yes\r")
            self.terminal.read_until("filled only")
            self.assertIn("JIS_BUFFER:git status", self.terminal.inspect())
        finally:
            rc.write_text(self.rc_template % ("", ROOT))

    def test_large_completion_registry_and_internal_function(self):
        self.terminal.close()
        rc = Path(self.tmp.name) / ".zshrc"
        setup = "for i in {1..2000}; do functions[_completion_registry_long_name_$i]='true'; done\nfunctions[_gti]='echo JIS_INTERNAL_FUNCTION'"
        rc.write_text(self.rc_template % (setup, ROOT))
        try:
            self.terminal = Terminal(self.env)
            t = self.terminal
            t.send("gti status\r")
            t.read_until("Do you mean git status")
            t.send("yes\r")
            t.read_until("filled only")
            self.assertIn("JIS_BUFFER:git status", t.inspect())
            t.send("\x03")
            t.read_until("JIS> ")
            t.drain()
            t.send("_gti status\r")
            t.read_until("\r\nJIS_INTERNAL_FUNCTION\r\n")
        finally:
            rc.write_text(self.rc_template % ("", ROOT))


if __name__ == "__main__":
    unittest.main(verbosity=2)

import os
import re
import shlex
import shutil
import subprocess
import select
import time
from collections import OrderedDict
from .types import Candidate
from .policy import simple

SUBCOMMANDS = {
    "git": "add status commit checkout switch restore branch diff log fetch pull push merge rebase stash tag remote clone init show reset clean cherry-pick worktree config bisect blame ls-files rev-parse".split(),
    "npm": "install run test start build ci audit update uninstall init publish outdated list cache config exec".split(),
    "docker": "ps images run build compose pull push logs exec inspect start stop restart rm rmi volume network container info version".split(),
    "conda": "activate deactivate install remove update create list info env search clean config run".split(),
    "kubectl": "get describe apply delete logs exec edit create scale rollout config version explain port-forward".split(),
    "pip": "install uninstall list show freeze check download cache index wheel".split(),
}
COMMON = {"git", "python", "python3", "ls", "cd", "cat", "echo", "pwd", "mkdir", "grep", "rg", "find", "curl", "npm", "docker", "conda", "pip", "ssh"}


def distance(a: str, b: str) -> int:
    """Optimal string alignment distance, including adjacent transpositions."""
    if abs(len(a) - len(b)) > 2:
        return 3
    old2 = None
    old = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            value = min(row[-1] + 1, old[j] + 1, old[j - 1] + (ca != cb))
            if old2 is not None and i > 1 and j > 1 and ca == b[j-2] and a[i-2] == cb:
                value = min(value, old2[j-2] + 1)
            row.append(value)
        old2, old = old, row
    return old[-1]


class CommandIndex:
    def __init__(self):
        self.cache = OrderedDict()
        self.trusted_git = shutil.which("git", path=os.environ.get("PATH", ""))

    def names(self, path, cwd):
        # Relative PATH entries are resolved against the requesting terminal.
        key = tuple(os.path.abspath(os.path.join(cwd, p)) for p in path.split(os.pathsep))
        now = time.monotonic()
        entry = self.cache.get(key)
        if entry and now - entry[0] < 30:
            self.cache.move_to_end(key)
            return entry[1]
        names = set()
        scanned = 0
        for directory in key[:64]:
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        scanned += 1
                        if scanned > 20000:
                            break
                        if entry.is_file() and os.access(entry.path, os.X_OK):
                            names.add(entry.name)
            except OSError:
                continue
            if scanned > 20000:
                break
        self.cache[key] = (now, names)
        if len(self.cache) > 16:
            self.cache.popitem(last=False)
        return names


class TypoProvider:
    def __init__(self, index):
        self.index = index
        self.alias_cache = OrderedDict()

    def git_aliases(self, context):
        key = (context.cwd, context.path)
        cached = self.alias_cache.get(key)
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
        aliases = set()
        # A typo request must not execute an arbitrary "git" supplied via its
        # PATH. Resolve this read-only helper once from the daemon startup PATH.
        executable = self.index.trusted_git
        if executable:
            try:
                with subprocess.Popen([executable, "config", "--get-regexp", r"^alias\."],
                                      cwd=context.cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      env={**os.environ, "PATH": os.environ.get("PATH", "")}) as process:
                    output = bytearray()
                    deadline = time.monotonic() + .06
                    while True:
                        remaining = deadline-time.monotonic()
                        if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                            process.kill(); process.wait()
                            return None
                        chunk = os.read(process.stdout.fileno(), min(4096, 32769-len(output)))
                        if not chunk:
                            break
                        output.extend(chunk)
                        if len(output) > 32768:
                            process.kill(); process.wait()
                            return None
                    # Kill inside the context: Popen.__exit__ waits for the
                    # child, so catching a timeout outside could hang first.
                    try:
                        process.wait(timeout=max(.001, deadline-time.monotonic()))
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                        return None
                aliases = {line.split()[0][6:] for line in output.decode().splitlines() if line.startswith("alias.")}
            except (OSError, UnicodeError, subprocess.TimeoutExpired):
                if 'process' in locals() and process.poll() is None:
                    process.kill(); process.wait()
                # Configuration unavailable: suppress subcommand correction.
                return None
        self.alias_cache[key] = (time.monotonic(), aliases)
        if len(self.alias_cache) > 32:
            self.alias_cache.popitem(last=False)
        return aliases

    def generate(self, context):
        if not simple(context.buffer):
            return []
        matches = list(re.finditer(r"\S+", context.buffer))
        try:
            words = shlex.split(context.buffer)
        except ValueError:
            return []
        if not words:
            return []
        head = words[0]
        names = self.index.names(context.path, context.cwd) | set(context.known)
        position = 0
        options = names
        if head in names:
            if head not in SUBCOMMANDS or len(words) < 2 or words[1].startswith("-"):
                return []
            # Unknown git subcommands can be user aliases/extensions. Don't guess
            # unless an actual adjacent typo exists; callers can disable corrections.
            options = set(SUBCOMMANDS[head]) | {n[4:] for n in names if n.startswith("git-")} if head == "git" else set(SUBCOMMANDS[head])
            position = 1
            if words[1] in options:
                return []
            if head == "git":
                aliases = self.git_aliases(context)
                if aliases is None or words[1] in aliases:
                    return []
        elif "/" in head or "=" in head or len(head) < 2:
            return []
        token = words[position]
        if matches[position].group() != token or len(token) > 64:
            return []
        results = []
        max_distance = 1 if len(token) <= 4 else 2
        for name in sorted(options):
            if abs(len(name)-len(token)) > max_distance:
                continue
            d = distance(token, name)
            if not 0 < d <= max_distance:
                continue
            start, end = matches[position].span()
            command = context.buffer[:start] + name + context.buffer[end:]
            similarity = 1 - d / max(len(token), len(name))
            results.append(Candidate(command, "correction", "typo", {
                "similarity": similarity, "distance": d,
                "common": float(name in COMMON or position == 1),
            }))
        return sorted(results, key=lambda c: (c.features["distance"], -c.features["common"], -c.features["similarity"], c.command))[:8]


class HistoryProvider:
    def __init__(self, store):
        self.store = store

    def generate(self, context):
        if not context.buffer or not simple(context.buffer):
            return []
        now = time.time()
        grouped = {}
        for _, session, cwd, command, previous, _, stamp in self.store.retrieve(context):
            if command == context.buffer:
                continue
            features = grouped.setdefault(command, {"session": 0, "cwd": 0, "transition": 0, "frequency": 0, "recency": 0})
            features["session"] = max(features["session"], float(session == context.session))
            features["cwd"] = max(features["cwd"], float(cwd == context.cwd))
            features["transition"] = max(features["transition"], float(bool(context.previous) and previous == context.previous and session == context.session))
            features["frequency"] += 1
            features["recency"] = max(features["recency"], 2 ** (-max(0, now - stamp) / 604800))
        return [Candidate(command, "completion", "history", f) for command, f in grouped.items()]

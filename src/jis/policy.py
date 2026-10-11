import re
import shlex
from pathlib import PurePath

# These guards constrain suggestions/learning; JIS never executes commands.
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
SECRET = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|private[_-]?key)"
    r"[\"']?\s*(?:=|:|\s)|\b(?:sk-|ghp_|github_pat_|AKIA)[A-Za-z0-9_-]{12,}"
    r"|\b(?:https?|ftp)://[^\s/:]+:[^\s/@]+@|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
COMPLEX = re.compile(r"[;&|<>`$(){}\n]")


def learnable(command: str) -> bool:
    return bool(command and len(command) <= 4096 and not command[0].isspace()
                and not CONTROL.search(command) and not SECRET.search(command)
                and not any(0xD800 <= ord(c) <= 0xDFFF for c in command))


def simple(command: str) -> bool:
    return learnable(command) and not COMPLEX.search(command)


def risky(command: str) -> bool:
    try:
        words = shlex.split(command)
    except ValueError:
        return True
    if not words:
        return True
    head = PurePath(words[0]).name
    if head in {"rm", "rmdir", "sudo", "dd", "mkfs", "shutdown", "reboot", "kill", "killall",
                "env", "command", "exec", "nohup", "xargs", "doas"} or head.startswith("mkfs."):
        return True
    if head == "git" and any(w in {"reset", "clean", "push"} for w in words[1:]):
        return True
    if head in {"docker", "kubectl"} and any(w in {"rm", "rmi", "delete", "prune"} for w in words[1:]):
        return True
    return False


def eligible(candidate, context) -> bool:
    if not simple(candidate.command):
        return False
    # Correct spelling only; preserving an explicitly typed rm command is allowed.
    if candidate.kind == "completion":
        return candidate.command.startswith(context.buffer) and not risky(candidate.command)
    return candidate.kind == "correction"

"""v1 JSON Lines API + percent-escaped tab protocol for fork-free zsh."""
import json
import re
from urllib.parse import unquote

MAX_FRAME = 32768
FIELDS = ("id", "op", "session", "cwd", "previous", "buffer", "status", "path", "known")


def encode_field(value):
    return "=" + str(value).replace("%", "%25").replace("\t", "%09").replace("\n", "%0A").replace("\r", "%0D")


def decode_frame(data):
    line = data.decode("utf-8").rstrip("\n")
    if line.startswith("{"):
        request = json.loads(line)
        if not isinstance(request, dict):
            raise ValueError("Expected request object")
        return request, False
    parts = line.split("\t")
    if len(parts) != len(FIELDS) or any(not p.startswith("=") for p in parts):
        raise ValueError("Invalid shell frame")
    request = dict(zip(FIELDS, (unquote(p[1:]) for p in parts)))
    request["status"] = int(request["status"] or 0)
    request["known"] = request["known"].splitlines()
    return request, True


def encode_response(response, shell=False):
    if shell:
        values = (response.get("id", "0"), response.get("kind", "none"),
                  response.get("command", ""), response.get("reason", ""))
        return ("\t".join(encode_field(v) for v in values) + "\n").encode()
    data = (json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    if len(data) > MAX_FRAME and "candidates" in response:
        response = {**response, "candidates": [], "evidence_truncated": True}
        data = (json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    return data


def validate(request):
    if set(request) - set(FIELDS):
        raise ValueError("Unknown request field")
    for key, limit in {"id": 64, "op": 20, "session": 128, "cwd": 4096,
                       "buffer": 4096, "previous": 4096, "path": 8192}.items():
        value = request.get(key, "")
        if not isinstance(value, str) or len(value) > limit or "\x00" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError(f"Invalid {key}")
        if key in {"id", "op", "session", "cwd", "path"} and re.search(r"[\x00-\x1f\x7f-\x9f]", value):
            raise ValueError(f"Control character in {key}")
    if request.get("op") not in {"hello", "ping", "suggest", "correct", "record", "stats", "stop"}:
        raise ValueError("Unknown operation")
    names = request.get("known", [])
    if not isinstance(names, list) or len(names) > 4096 or any(not isinstance(n, str) or len(n) > 128 or re.search(r"[\s\x00-\x1f\x7f-\x9f\ud800-\udfff]", n) for n in names):
        raise ValueError("Invalid shell command list")
    status = request.get("status", 0)
    if type(status) is not int or not 0 <= status <= 255:
        raise ValueError("Invalid exit status")

import json
import socket
import os
import struct
import stat
from .paths import state_dir
from .protocol import MAX_FRAME


def request(payload, timeout=.5):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        path = state_dir() / "jis.sock"
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("Untrusted JIS socket")
        connection.connect(str(path))
        if hasattr(socket, "SO_PEERCRED"):
            _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != os.getuid():
                raise RuntimeError("Untrusted JIS daemon peer")
        connection.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        data = bytearray()
        while b"\n" not in data:
            chunk = connection.recv(8192)
            if not chunk:
                raise ConnectionError("Daemon closed connection")
            data.extend(chunk)
            if len(data) > MAX_FRAME:
                raise ValueError("Response too large")
        return json.loads(data.split(b"\n", 1)[0])

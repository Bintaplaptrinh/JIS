import os
import stat
from pathlib import Path


def state_dir():
    return Path(os.environ.get("JIS_STATE_DIR", str(Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "jis")))


def prepare_state():
    os.umask(0o077)
    path = state_dir()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise RuntimeError("JIS state directory must be owned by the current user and not a symlink")
    path.chmod(0o700)
    return path


def private_file(path, mode="a", create=True):
    """Open only an owned, regular, single-link file; never follow a symlink."""
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    if create:
        flags |= os.O_CREAT
    if mode == "a":
        flags |= os.O_APPEND
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise RuntimeError("JIS refuses unowned, special or multiply linked state files")
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, mode)
    except BaseException:
        os.close(fd)
        raise

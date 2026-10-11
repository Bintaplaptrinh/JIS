import sqlite3
import time
from pathlib import Path
from .policy import learnable
from .paths import private_file


class HistoryStore:
    """Bounded observations, indexed per session/directory/prefix; no imported history."""
    def __init__(self, path: Path, limit: int = 20000):
        path = Path(path)
        for file in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            if file == path or file.exists() or file.is_symlink():
                with private_file(file, create=file == path):
                    pass
        self.limit = limit
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA busy_timeout=250")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, session TEXT NOT NULL, cwd TEXT NOT NULL,
                command TEXT COLLATE BINARY NOT NULL, previous TEXT NOT NULL,
                status INTEGER NOT NULL, stamp REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS obs_prefix ON observations(command);
            CREATE INDEX IF NOT EXISTS obs_cwd ON observations(cwd,command);
            CREATE INDEX IF NOT EXISTS obs_session ON observations(session,command);
            CREATE INDEX IF NOT EXISTS obs_previous ON observations(previous,command);
        """)
        self.count = self.db.execute("SELECT count(*) FROM observations").fetchone()[0]
        if self.count > limit:
            with self.db:
                self.db.execute("DELETE FROM observations WHERE id IN (SELECT id FROM observations ORDER BY id LIMIT ?)", (self.count-limit,))
            self.count = limit
        for suffix in ("-wal", "-shm"):
            file = Path(str(path) + suffix)
            if file.exists():
                with private_file(file, create=False):
                    pass

    def record(self, session, cwd, command, previous="", status=0):
        if not learnable(command):
            return False
        if not learnable(previous):
            previous = ""
        with self.db:
            self.db.execute("INSERT INTO observations(session,cwd,command,previous,status,stamp) VALUES(?,?,?,?,?,?)",
                            (session, cwd, command, previous, status, time.time()))
            self.count += 1
            if self.count > self.limit:
                excess = self.count - self.limit
                self.db.execute("DELETE FROM observations WHERE id IN (SELECT id FROM observations ORDER BY id LIMIT ?)", (excess,))
                self.count = self.limit
        return True

    def retrieve(self, context, limit=96):
        prefix = context.buffer
        # BINARY range uses indexes and treats % and _ literally.
        bounds = (prefix, prefix + "\U0010ffff")
        rows = []
        queries = [
            ("session=?", (context.session,)),
            ("cwd=?", (context.cwd,)),
            ("previous=?", (context.previous,)),
            ("1=1", ()),
        ]
        seen = set()
        for where, params in queries:
            for row in self.db.execute(
                f"SELECT id,session,cwd,command,previous,status,stamp FROM observations "
                f"WHERE {where} AND command>=? AND command<? AND status=0 ORDER BY id DESC LIMIT ?",
                (*params, *bounds, limit),
            ):
                if row[0] not in seen:
                    rows.append(row)
                    seen.add(row[0])
        return rows

    def close(self):
        self.db.close()

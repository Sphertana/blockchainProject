"""Demo web accounts stored in SQLite. Passwords are Argon2-hashed. These are
web logins only — the teacher is the sole holder of a blockchain private key."""

import os
import sqlite3
from pathlib import Path

from pwdlib import PasswordHash

DB = Path("data/app.db")
_hasher = PasswordHash.recommended()

# (username, password env var, role, address env var)
_SEED = [
    ("teacher", "TEACHER_PASSWORD", "teacher", "TEACHER_ADDRESS"),
    ("student1", "STUDENT1_PASSWORD", "student", "STUDENT1_ADDRESS"),
    ("student2", "STUDENT2_PASSWORD", "student", "STUDENT2_ADDRESS"),
]


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB)


def init_db() -> None:
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS users "
            "(username TEXT PRIMARY KEY, pw_hash TEXT, role TEXT, address TEXT)"
        )
        for username, pw_var, role, addr_var in _SEED:
            exists = c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
            if not exists:
                password = os.environ.get(pw_var, username)
                address = os.environ.get(addr_var, "")
                c.execute(
                    "INSERT INTO users VALUES (?,?,?,?)",
                    (username, _hasher.hash(password), role, address),
                )


def authenticate(username: str, password: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT username, pw_hash, role, address FROM users WHERE username=?",
            (username,),
        ).fetchone()
    if not row or not _hasher.verify(password, row[1]):
        return None
    return {"username": row[0], "role": row[2], "address": row[3]}


def get_user(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT username, role, address FROM users WHERE username=?", (username,)
        ).fetchone()
    return {"username": row[0], "role": row[1], "address": row[2]} if row else None

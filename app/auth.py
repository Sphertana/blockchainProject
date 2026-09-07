"""Web accounts stored in SQLite.

Each account carries two independent secrets:
  * a password (Argon2 hash) that unlocks the web session;
  * an Ethereum key pair, kept as an encrypted keystore, that signs the user's
    own transactions — for a student, their enrollment request.

The gateway is therefore a *custodial* wallet: acceptable for a classroom demo
on a zero-value private chain, and stated as such in the report. Real identity
(the username) stays off-chain; the chain only ever sees the address.
"""

import json
import os
import re
import sqlite3
from pathlib import Path

from eth_account import Account
from pwdlib import PasswordHash

DB = Path("data/app.db")
_hasher = PasswordHash.recommended()

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD = 12
MAX_PASSWORD = 128
_DUMMY_HASH = _hasher.hash("not-a-real-password")

# (username, password env var, role, private-key env var)
_SEED = [
    ("teacher", "TEACHER_PASSWORD", "teacher", "TEACHER_PRIVATE_KEY"),
    ("student1", "STUDENT1_PASSWORD", "student", "STUDENT1_PRIVATE_KEY"),
    ("student2", "STUDENT2_PASSWORD", "student", "STUDENT2_PRIVATE_KEY"),
]


class RegistrationError(ValueError):
    """Rejected sign-up, carrying a message meant for the end user."""


def _wallet_secret() -> str:
    return os.environ.get("WALLET_SECRET") or os.environ.get("SESSION_SECRET", "dev")


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    DB.parent.chmod(0o700)
    connection = sqlite3.connect(DB, timeout=10)
    DB.chmod(0o600)
    return connection


def init_db() -> None:
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, role TEXT NOT NULL, "
            "address TEXT NOT NULL, keystore TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        columns = {row[1] for row in c.execute("PRAGMA table_info(users)")}
        for name, decl in (("keystore", "TEXT"), ("created_at", "TEXT")):
            if name not in columns:  # database created before wallets existed
                c.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
        for username, pw_var, role, key_var in _SEED:
            key = os.environ.get(key_var)
            row = c.execute(
                "SELECT keystore FROM users WHERE username=?", (username,)
            ).fetchone()
            if row is None:
                if key:  # no demo key configured: skip rather than create a keyless account
                    _insert(c, username, os.environ.get(pw_var, username), role, key)
            elif not row[0] and key:
                account = Account.from_key(key)
                keystore = Account.encrypt(key, _wallet_secret(), kdf="scrypt")
                c.execute(
                    "UPDATE users SET address=?, keystore=? WHERE username=?",
                    (account.address, json.dumps(keystore), username),
                )


def _insert(c: sqlite3.Connection, username: str, password: str, role: str, key: str) -> dict:
    account = Account.from_key(key)
    keystore = Account.encrypt(key, _wallet_secret(), kdf="scrypt")
    c.execute(
        "INSERT INTO users (username, pw_hash, role, address, keystore) VALUES (?,?,?,?,?)",
        (username, _hasher.hash(password), role, account.address, json.dumps(keystore)),
    )
    return {"username": username, "role": role, "address": account.address}


def register(username: str, password: str, confirm: str) -> dict:
    """Create a student account with a freshly generated wallet."""
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        raise RegistrationError(
            "Identifiant invalide : 3 à 32 caractères (minuscules, chiffres, . _ ou -)."
        )
    if len(password) < MIN_PASSWORD:
        raise RegistrationError(f"Le mot de passe doit faire au moins {MIN_PASSWORD} caractères.")
    if len(password) > MAX_PASSWORD:
        raise RegistrationError(f"Le mot de passe ne peut pas dépasser {MAX_PASSWORD} caractères.")
    if password != confirm:
        raise RegistrationError("Les deux mots de passe ne correspondent pas.")
    with _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise RegistrationError("Cet identifiant est déjà pris.")
        return _insert(c, username, password, "student", Account.create().key.hex())


def authenticate(username: str, password: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT username, pw_hash, role, address FROM users WHERE username=?",
            (username.strip().lower(),),
        ).fetchone()
    if len(password) > MAX_PASSWORD:
        return None
    if not row:
        _hasher.verify(password, _DUMMY_HASH)
        return None
    if not _hasher.verify(password, row[1]):
        return None
    return {"username": row[0], "role": row[2], "address": row[3]}


def get_user(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT username, role, address FROM users WHERE username=?", (username,)
        ).fetchone()
    return {"username": row[0], "role": row[1], "address": row[2]} if row else None


def private_key(username: str) -> str:
    """Decrypt the account's signing key. Raises if the account has no wallet."""
    with _conn() as c:
        row = c.execute("SELECT keystore FROM users WHERE username=?", (username,)).fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"no wallet for {username}")
    return "0x" + Account.decrypt(json.loads(row[0]), _wallet_secret()).hex()


def names_by_address() -> dict[str, str]:
    """Address → username, so the teacher sees people instead of hex strings."""
    with _conn() as c:
        return {addr: name for addr, name in c.execute("SELECT address, username FROM users")}

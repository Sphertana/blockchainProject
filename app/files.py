"""Course files live on the server disk; only their SHA-256 goes on-chain."""

import hashlib
import re
import uuid
from pathlib import Path

FILES = Path("data/files")


def save(data: bytes, filename: str) -> tuple[str, bytes]:
    FILES.mkdir(parents=True, exist_ok=True)
    basename = Path(filename).name
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", basename) or "document"
    ref = f"{uuid.uuid4().hex}_{safe_name}"
    (FILES / ref).write_bytes(data)
    return ref, hashlib.sha256(data).digest()


def read(ref: str) -> bytes | None:
    path = FILES / ref
    return path.read_bytes() if path.exists() else None


def delete(ref: str) -> None:
    (FILES / ref).unlink(missing_ok=True)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()

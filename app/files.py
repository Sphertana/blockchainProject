"""Course files live on the server disk; only their SHA-256 goes on-chain."""

import hashlib
import re
import uuid
from pathlib import Path

FILES = Path("data/files")
REF_RE = re.compile(r"^[0-9a-f]{32}_[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


def _path(ref: str) -> Path | None:
    if not REF_RE.fullmatch(ref):
        return None
    root = FILES.resolve()
    path = (root / ref).resolve()
    return path if path.parent == root else None


def save(data: bytes, filename: str) -> tuple[str, bytes]:
    FILES.mkdir(parents=True, exist_ok=True, mode=0o700)
    FILES.chmod(0o700)
    basename = Path(filename).name
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", basename).lstrip(".")[:120] or "document"
    ref = f"{uuid.uuid4().hex}_{safe_name}"
    path = FILES / ref
    path.write_bytes(data)
    path.chmod(0o600)
    return ref, hashlib.sha256(data).digest()


def read(ref: str) -> bytes | None:
    path = _path(ref)
    return path.read_bytes() if path and path.is_file() else None


def delete(ref: str) -> None:
    path = _path(ref)
    if path:
        path.unlink(missing_ok=True)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()

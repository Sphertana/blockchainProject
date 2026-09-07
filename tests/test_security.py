from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import files, security


def test_csrf_token_is_required_and_bound_to_session():
    request = SimpleNamespace(session={})
    token = security.csrf_token(request)
    security.require_csrf(request, token)
    with pytest.raises(HTTPException) as exc:
        security.require_csrf(request, "wrong-token")
    assert exc.value.status_code == 403


def test_production_rejects_weak_secrets(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SESSION_SECRET", "dev-change-me")
    monkeypatch.setenv("WALLET_SECRET", "w" * 64)
    monkeypatch.setenv("GRADE_ENCRYPTION_KEY", "12ab34cd56ef7890" * 4)
    monkeypatch.setenv("COOKIE_SECURE", "true")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        security.validate_runtime()


def test_file_store_rejects_paths_outside_its_root(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "FILES", tmp_path / "files")
    ref, digest = files.save(b"proof", "../../notes.pdf")
    assert files.read(ref) == b"proof"
    assert files.read("../outside") is None
    assert files.read("/etc/passwd") is None
    assert files.sha256(b"proof") == digest
    assert (files.FILES / ref).stat().st_mode & 0o777 == 0o600
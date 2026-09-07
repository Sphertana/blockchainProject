"""Authenticated encryption for grades stored on the transparent ledger."""

import base64
import os
import secrets

from Crypto.Cipher import AES

PREFIX = "enc:v1:"


def _key() -> bytes:
    raw = os.environ.get("GRADE_ENCRYPTION_KEY", "")
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise RuntimeError("GRADE_ENCRYPTION_KEY must be 64 hexadecimal characters") from exc
    if len(key) != 32:
        raise RuntimeError("GRADE_ENCRYPTION_KEY must be 64 hexadecimal characters")
    return key


def encrypt_grade(student: str, value: str) -> str:
    nonce = secrets.token_bytes(12)
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=nonce)
    cipher.update(student.lower().encode())
    ciphertext, tag = cipher.encrypt_and_digest(value.encode())
    payload = base64.urlsafe_b64encode(nonce + tag + ciphertext).decode()
    return PREFIX + payload


def decrypt_grade(student: str, stored: str) -> str:
    if not stored.startswith(PREFIX):
        return stored  # data produced before encryption was introduced
    try:
        payload = base64.urlsafe_b64decode(stored[len(PREFIX) :].encode())
        nonce, tag, ciphertext = payload[:12], payload[12:28], payload[28:]
        cipher = AES.new(_key(), AES.MODE_GCM, nonce=nonce)
        cipher.update(student.lower().encode())
        return cipher.decrypt_and_verify(ciphertext, tag).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("encrypted grade failed authentication") from exc
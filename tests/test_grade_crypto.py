import pytest

from app import grade_crypto


@pytest.fixture(autouse=True)
def grade_key(monkeypatch):
    monkeypatch.setenv("GRADE_ENCRYPTION_KEY", "12ab34cd56ef789012ab34cd56ef789012ab34cd56ef789012ab34cd56ef7890")


def test_grade_is_authenticated_and_not_visible_in_ciphertext():
    student = "0x1234567890abcdef1234567890abcdef12345678"
    encrypted = grade_crypto.encrypt_grade(student, "16/20")
    assert encrypted.startswith("enc:v1:")
    assert "16/20" not in encrypted
    assert grade_crypto.decrypt_grade(student, encrypted) == "16/20"


def test_another_student_cannot_decrypt_grade():
    encrypted = grade_crypto.encrypt_grade("0xAlice", "A")
    with pytest.raises(ValueError, match="failed authentication"):
        grade_crypto.decrypt_grade("0xBob", encrypted)


def test_legacy_plaintext_grade_remains_readable():
    assert grade_crypto.decrypt_grade("0xAlice", "A") == "A"
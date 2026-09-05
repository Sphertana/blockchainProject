from pathlib import Path

from app import files


def test_save_sanitizes_filename_and_preserves_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "FILES", tmp_path)
    content = b"course material"

    ref, digest = files.save(content, "../../cours final\r\n.pdf")

    assert "/" not in ref
    assert "\\" not in ref
    assert "\r" not in ref
    assert "\n" not in ref
    assert files.read(ref) == content
    assert digest == files.sha256(content)
    assert Path(tmp_path, ref).is_file()
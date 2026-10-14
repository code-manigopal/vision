"""Shared test setup: the voice word files (data/) and Mani's presenter doodle (vault/presenter) are his, on his Mac, and change; tests must not read them."""

import pytest

from vision.masters import slides, tamil_say


@pytest.fixture(autouse=True)
def _own_voice_word_files(tmp_path, monkeypatch):
    monkeypatch.setattr(tamil_say, "LEARNED", tmp_path / "voice_words.json")
    monkeypatch.setattr(tamil_say, "FIXES", tmp_path / "voice_fixes.json")
    monkeypatch.setattr(slides, "PRESENTER", tmp_path / "presenter")

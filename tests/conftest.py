"""Shared test setup: the voice word files and the Groq usage ledger (data/) and Mani's presenter doodle (vault/presenter) are his, on his Mac, and change; tests must not read them."""

import pytest

from vision.masters import slides, tamil_say
from vision.services import groq_budget


@pytest.fixture(autouse=True)
def _own_voice_word_files(tmp_path, monkeypatch):
    monkeypatch.setattr(tamil_say, "LEARNED", tmp_path / "voice_words.json")
    monkeypatch.setattr(tamil_say, "FIXES", tmp_path / "voice_fixes.json")
    monkeypatch.setattr(slides, "PRESENTER", tmp_path / "presenter")
    monkeypatch.setattr(groq_budget, "FILE", tmp_path / "groq_usage.json")       # the live Groq ledger is never touched by a test

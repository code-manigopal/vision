"""Configuration: non-secret settings from config.yaml, secrets from .env.

You only ever edit two files:
    config.yaml  - cities, schedules, which masters are on, trust levels, models
    .env         - API keys and tokens (never shared, never committed)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(os.getenv("VISION_HOME", Path(__file__).resolve().parent.parent))


class MasterConfig(BaseModel):
    enabled: bool = True
    trust: str = "OBSERVE"          # OBSERVE | SUGGEST | ACT | HOLD
    mode: str = "stub"              # stub = demo agents until the real master is built; live = real agents
    cycle_minutes: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class VisionConfig(BaseModel):
    owner: str = "Mani"
    home_city: str = "Leamington, ON"
    timezone: str = "America/Toronto"
    host: str = "127.0.0.1"
    port: int = 8765
    brief_times: list[str] = Field(default_factory=lambda: ["06:00", "18:00"])
    cycle_minutes: int = 15


class LLMConfig(BaseModel):
    local_base_url: str = "http://localhost:1234/v1"
    local_model: str = ""
    cloud_provider: str = "anthropic"
    cloud_model: str = ""
    writer_base_url: str = "https://api.groq.com/openai/v1"
    writer_model: str = ""


class Config(BaseModel):
    vision: VisionConfig = Field(default_factory=VisionConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    masters: dict[str, MasterConfig] = Field(default_factory=dict)
    voice: dict[str, Any] = Field(default_factory=dict)
    telegram: dict[str, Any] = Field(default_factory=dict)

    def master(self, master_id: str) -> MasterConfig:
        return self.masters.get(master_id, MasterConfig())

    def cycle_minutes(self, master_id: str) -> int:
        return self.master(master_id).cycle_minutes or self.vision.cycle_minutes


def load_config(path: Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    path = path or ROOT / "config.yaml"
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    return Config.model_validate(raw or {})


def secret(name: str) -> str | None:
    """Read a key from the environment (.env). Returns None when unset or left blank."""
    val = os.getenv(name, "").strip()
    return val or None

"""
Configuration loading and validation using Pydantic.

Loads:
 - Environment variables from .env (via python-dotenv)
 - Group/session config from config.yaml
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ─── Environment settings (.env) ─────────────────────────────────────────────

class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_api_id: int
    telegram_api_hash: str
    grok_api_key: str
    grok_api_base_url: str = "https://api.x.ai/v1"
    grok_model: str = "grok-3-latest"
    log_level: str = "INFO"


# ─── YAML config models ───────────────────────────────────────────────────────

class SessionConfig(BaseModel):
    name: str
    string_session: str
    is_admin: bool = False
    persona: Optional[str] = None


class GroupConfig(BaseModel):
    id: int
    name: str
    participants: list[str]          # list of session names
    prompt: str

    @field_validator("participants")
    @classmethod
    def participants_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Group must have at least one participant")
        return v


class YamlConfig(BaseModel):
    delay_min: float = Field(default=8.0, ge=1.0)
    delay_max: float = Field(default=25.0, ge=1.0)
    context_window: int = Field(default=30, ge=5)
    sessions: list[SessionConfig]
    groups: list[GroupConfig]

    @field_validator("sessions")
    @classmethod
    def sessions_not_empty(cls, v: list[SessionConfig]) -> list[SessionConfig]:
        if not v:
            raise ValueError("At least one session must be defined")
        return v

    @field_validator("delay_max")
    @classmethod
    def delay_max_gt_min(cls, v: float, info) -> float:
        delay_min = info.data.get("delay_min", 0)
        if v <= delay_min:
            raise ValueError("delay_max must be greater than delay_min")
        return v


# ─── Combined app config ──────────────────────────────────────────────────────

class AppConfig(BaseModel):
    env: EnvSettings
    yaml: YamlConfig

    @property
    def sessions_by_name(self) -> dict[str, SessionConfig]:
        return {s.name: s for s in self.yaml.sessions}

    @property
    def admin_session(self) -> Optional[SessionConfig]:
        for s in self.yaml.sessions:
            if s.is_admin:
                return s
        return None


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    """Load and validate the full application configuration."""
    env = EnvSettings()

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. "
            "Copy config.yaml.example to config.yaml and fill in your values."
        )

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    yaml_cfg = YamlConfig.model_validate(raw)

    # Validate that all group participants exist in sessions
    session_names = {s.name for s in yaml_cfg.sessions}
    for group in yaml_cfg.groups:
        unknown = set(group.participants) - session_names
        if unknown:
            raise ValueError(
                f"Group '{group.name}' references unknown session(s): {unknown}"
            )

    return AppConfig(env=env, yaml=yaml_cfg)

"""Configuration management for agenttop."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CONFIG_DIR = Path.home() / ".agenttop"
CONFIG_FILE = CONFIG_DIR / "config.toml"
DB_PATH = CONFIG_DIR / "agenttop.db"

# Default paths for AI tool data
CLAUDE_DIR = Path.home() / ".claude"
CURSOR_DIR = Path.home() / ".cursor"
KIRO_DIR = Path.home() / "Library" / "Application Support" / "Kiro"


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = "ollama"
    model: str = "ollama/gemma3:4b"
    api_key: str = ""
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str = "http://localhost:11434"
    base_url_env: str = ""
    max_budget_per_day: float = 1.0  # USD


class ProxyConfig(BaseModel):
    """Proxy collector configuration."""

    enabled: bool = False
    port: int = 9120
    forward_urls: dict[str, str] = Field(default_factory=dict)


class Config(BaseModel):
    """Top-level agenttop configuration."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    refresh_interval: int = 5  # seconds
    claude_dir: Path = CLAUDE_DIR
    cursor_dir: Path = CURSOR_DIR
    kiro_dir: Path = KIRO_DIR


def _apply_env_overrides(config: Config) -> Config:
    """Apply AGENTTOP_LLM_* env var overrides. Returns a new Config (immutable)."""
    import os

    overrides: dict[str, Any] = {}
    provider = os.environ.get("AGENTTOP_LLM_PROVIDER")
    model = os.environ.get("AGENTTOP_LLM_MODEL")
    base_url = os.environ.get("AGENTTOP_LLM_BASE_URL")

    if provider:
        overrides["provider"] = provider
    if model:
        overrides["model"] = model
    if base_url:
        overrides["base_url"] = base_url

    if not overrides:
        return config

    llm_data = config.llm.model_dump()
    llm_data.update(overrides)
    return config.model_copy(update={"llm": LLMConfig(**llm_data)})


def load_config() -> Config:
    """Load configuration from ~/.agenttop/config.toml, falling back to defaults."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "rb") as f:
            data: dict[str, Any] = tomllib.load(f)
        config = Config(**data)
    else:
        config = Config()
    return _apply_env_overrides(config)


def ensure_config_dir() -> None:
    """Create ~/.agenttop/ if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


DEFAULT_CONFIG_TOML = """\
# agenttop configuration
# See https://github.com/vicarious11/agenttop for docs
#
# LLM configuration for the AI-powered optimizer.
# agenttop web ensures the LLM is ready before starting.

# ── Ollama (default — free, local, private) ──
# Install: brew install ollama && ollama pull gemma3:4b && ollama serve
# No API key needed. All analysis stays on your machine.
[llm]
provider = "ollama"
model = "ollama/gemma3:4b"
base_url = "http://localhost:11434"
max_budget_per_day = 1.0

# ── Anthropic (uncomment for cloud-powered analysis) ──
# [llm]
# provider = "anthropic"
# model = "claude-haiku-4-5-20251001"
# api_key_env = "ANTHROPIC_API_KEY"
# max_budget_per_day = 1.0

# ── OpenAI (uncomment to use) ──
# [llm]
# provider = "openai"
# model = "gpt-4o-mini"
# api_key_env = "OPENAI_API_KEY"
# max_budget_per_day = 1.0

# ── OpenRouter (uncomment to use) ──
# [llm]
# provider = "openrouter"
# model = "openrouter/google/gemini-2.0-flash-001"
# api_key_env = "OPENROUTER_API_KEY"
# base_url = "https://openrouter.ai/api/v1"
# max_budget_per_day = 1.0

[proxy]
enabled = false
port = 9120

# [proxy.forward_urls]
# anthropic = "https://api.anthropic.com"
# openai = "https://api.openai.com"

# Refresh interval for the dashboard (seconds)
# refresh_interval = 5

# ── Environment variable overrides ──
# These env vars override any config file values:
#   AGENTTOP_LLM_PROVIDER  — provider name (anthropic, openai, ollama, openrouter)
#   AGENTTOP_LLM_MODEL     — model identifier
#   AGENTTOP_LLM_BASE_URL  — custom API base URL
"""


def init_config() -> Path:
    """Write default config.toml if it doesn't exist. Returns the path."""
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(DEFAULT_CONFIG_TOML)
    return CONFIG_FILE

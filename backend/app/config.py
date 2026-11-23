"""Runtime settings, read once from environment variables (and a local .env file)."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_REPO_ROOT / "backend" / ".env")
load_dotenv()


def _csv(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))

    # "anthropic" in production (required by the hackathon brief). "groq" is a
    # free provider used only for local development / testing.
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "anthropic").strip().lower())
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-haiku-5-5"))
    groq_api_keys: List[str] = field(
        default_factory=lambda: _csv(os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", "")))
    )
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))

    max_output_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_OUTPUT_TOKENS", "700")))
    history_window: int = field(default_factory=lambda: int(os.getenv("HISTORY_WINDOW", "20")))
    max_agent_steps: int = field(default_factory=lambda: int(os.getenv("MAX_AGENT_STEPS", "6")))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "25")))
    # Soft deadline for one chat turn: after this, no further LLM/tool rounds start.
    turn_budget_s: float = field(default_factory=lambda: float(os.getenv("TURN_BUDGET_S", "40")))

    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", ""))
    cors_origins: List[str] = field(default_factory=lambda: _csv(os.getenv("CORS_ORIGINS", "*")) or ["*"])
    seed_demo_data: bool = field(
        default_factory=lambda: os.getenv("SEED_DEMO_DATA", "true").strip().lower() in {"1", "true", "yes"}
    )


settings = Settings()

# Haiku 5.5 list prices (USD per 1M tokens, prompts <= 100K tokens). Used only for
# the admin dashboard cost estimate.
PRICE_IN_PER_MTOK = 0.10
PRICE_OUT_PER_MTOK = 0.50

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from backend/.env so we can pick up
# OPENAI_API_KEY and OPENAI_MODEL_NAME exactly as you've defined them.
load_dotenv(BASE_DIR / ".env")


class Settings:
    """Application configuration loaded from environment variables."""

    def __init__(self) -> None:
        self.app_name: str = "LLM Expense Tracker"
        self.openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
        # Prefer your OPENAI_MODEL_NAME, but also fall back to OPENAI_MODEL if set.
        self.openai_model: str = (
            os.getenv("OPENAI_MODEL_NAME")
            or os.getenv("OPENAI_MODEL")
            or "gpt-4o-mini"
        )
        # Allow overriding the DB via DATABASE_URL, otherwise default to local SQLite.
        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:///./expenses.db")
        self.approval_token: str = os.getenv("APPROVAL_TOKEN", "change-me")
        self.approval_threshold: float = float(os.getenv("APPROVAL_THRESHOLD", "1000.0"))


settings = Settings()


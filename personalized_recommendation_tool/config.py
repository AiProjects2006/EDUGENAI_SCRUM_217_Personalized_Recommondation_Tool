"""Configuration settings for the Personalized Recommendation Tool."""

from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

_ROOT_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT_DIR / ".env"
_AI_SERVICE_ENV_FILE = _ROOT_DIR.parent / "EDUGENAI_SCRUM_53_Multi_Agent_Setup" / ".env"

if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)
if _AI_SERVICE_ENV_FILE.exists():
    load_dotenv(_AI_SERVICE_ENV_FILE, override=False)


def _as_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    tool_port: int = int(os.getenv("TOOL_PORT", "8001"))
    user_service_url: str = os.getenv("USER_SERVICE_URL", "http://localhost:8081").rstrip("/")
    course_service_url: str = os.getenv("COURSE_SERVICE_URL", "http://localhost:8082").rstrip("/")
    activity_service_url: str = os.getenv("ACTIVITY_SERVICE_URL", "http://localhost:8083").rstrip("/")
    enrollment_service_url: str = os.getenv("ENROLLMENT_SERVICE_URL", "http://localhost:8084").rstrip("/")
    settings_service_url: str = os.getenv(
        "SETTINGS_SERVICE_URL",
        os.getenv("ENROLLMENT_SERVICE_URL", "http://localhost:8084"),
    ).rstrip("/")
    progress_service_url: str = os.getenv("PROGRESS_SERVICE_URL", "http://localhost:8088").rstrip("/")

    http_timeout_seconds: float = float(os.getenv("SERVICE_HTTP_TIMEOUT_SECONDS", "2.5"))

    enable_llm: bool = _as_bool(os.getenv("RECOMMENDATION_ENABLE_LLM", "true"))
    llm_timeout_seconds: float = float(os.getenv("RECOMMENDATION_LLM_TIMEOUT_SECONDS", "4.0"))
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")


settings = Settings()

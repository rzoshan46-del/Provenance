import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass


def get_app_env() -> str:
    return (
        (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development")
        .strip()
        .lower()
    )


def is_production() -> bool:
    return get_app_env() == "production"


def get_auth_mode() -> str:
    mode = (os.getenv("AUTH_MODE") or "demo").strip().lower()
    if mode in {"google", "oauth", "google_oauth", "oidc"}:
        return "google"
    return "demo"


def google_auth_enabled() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def get_base_url() -> str:
    return (os.getenv("APP_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")


def get_session_secret() -> str:
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        if is_production():
            raise RuntimeError("SESSION_SECRET must be configured in production environments")
        return "provenance-demo-secret-key-change-in-production"
    return secret


def get_database_url() -> str:
    return (
        os.getenv("PROVENANCE_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("PROVENANCE_DB")
        or "data/app.db"
    )


def demo_mode_enabled() -> bool:
    return os.getenv("PROVENANCE_DEMO", "1") != "0"


def docs_enabled() -> bool:
    default = "0" if is_production() else "1"
    val = os.getenv("DOCS_ENABLED", default).strip().lower()
    return val in {"1", "true", "yes", "on"}


def ai_mode() -> str:
    return (os.getenv("PROVENANCE_LLM") or "off").strip().lower()

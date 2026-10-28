import os


def get_app_env() -> str:
    return (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development").strip().lower()


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
    return os.getenv("SESSION_SECRET") or "change-me-in-production"


def get_database_url() -> str:
    return os.getenv("PROVENANCE_DATABASE_URL") or os.getenv("PROVENANCE_DB") or "data/app.db"


def demo_mode_enabled() -> bool:
    return os.getenv("PROVENANCE_DEMO", "1") != "0"


def ai_mode() -> str:
    return (os.getenv("PROVENANCE_LLM") or "off").strip().lower()

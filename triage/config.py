import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    composio_api_key: str
    composio_user_id: str
    gemini_api_key: str
    gemini_model: str
    gemini_fallback_model: str


def load_config() -> Config:
    missing = [k for k in ("COMPOSIO_API_KEY", "GEMINI_API_KEY") if not os.getenv(k)]
    if missing:
        raise ConfigError(f"Missing in .env: {', '.join(missing)}")
    return Config(
        composio_api_key=os.environ["COMPOSIO_API_KEY"],
        composio_user_id=os.getenv("COMPOSIO_USER_ID", "default"),
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        gemini_fallback_model=os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
    )

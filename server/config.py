"""
GreenOps Server Configuration
All settings are read from environment variables with documented defaults.
"""
import os
from typing import Optional


class Config:

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://greenops:greenops@localhost:5432/greenops",
    )
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "20"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))

    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "CHANGE_THIS_IN_PRODUCTION")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

    AGENT_TOKEN_EXPIRATION_DAYS: Optional[int] = None

    LOGIN_RATE_LIMIT: int = int(os.getenv("LOGIN_RATE_LIMIT", "5"))
    LOGIN_RATE_WINDOW: int = int(os.getenv("LOGIN_RATE_WINDOW", "900"))

    IDLE_POWER_WATTS: float = float(os.getenv("IDLE_POWER_WATTS", "65"))
    ACTIVE_POWER_WATTS: float = float(os.getenv("ACTIVE_POWER_WATTS", "120"))
    ELECTRICITY_COST_PER_KWH: float = float(os.getenv("ELECTRICITY_COST_PER_KWH", "0.12"))

    HEARTBEAT_TIMEOUT_SECONDS: int = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "180"))
    IDLE_THRESHOLD_SECONDS: int = int(os.getenv("IDLE_THRESHOLD_SECONDS", "300"))

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "/app/logs/greenops.log")

    CORS_ORIGINS: list = os.getenv("CORS_ORIGINS", "*").split(",")

    ADMIN_INITIAL_PASSWORD: Optional[str] = os.getenv("ADMIN_INITIAL_PASSWORD")

    OFFLINE_CHECK_INTERVAL_SECONDS: int = int(
        os.getenv("OFFLINE_CHECK_INTERVAL_SECONDS", "60")
    )

    @classmethod
    def validate(cls) -> None:
        if not cls.DATABASE_URL:
            raise ValueError("DATABASE_URL must be set.")

        if cls.JWT_SECRET_KEY == "CHANGE_THIS_IN_PRODUCTION":
            if not cls.DEBUG:
                raise ValueError(
                    "JWT_SECRET_KEY must be changed from the default value in production. "
                    "Generate one with: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
            import logging
            logging.getLogger(__name__).warning(
                "SECURITY WARNING: Using default JWT_SECRET_KEY. "
                "This is only acceptable in local development (DEBUG=true)."
            )


config = Config()

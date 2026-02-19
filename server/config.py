"""
GreenOps Server Configuration
==============================
All settings are read from environment variables.  Defaults are documented
inline.  In Docker the environment is injected via the env_file directive in
docker-compose.yml.  Locally, export variables or use python-dotenv.
"""

import os
from typing import Optional


class Config:

    # ── Web server ────────────────────────────────────────────────────────────
    HOST: str  = os.getenv("HOST", "0.0.0.0")
    PORT: int  = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://greenops:greenops@localhost:5432/greenops",
    )
    # ThreadedConnectionPool parameters.
    # With workers=4, threads=2 (gthread) the server handles up to 8 concurrent
    # requests.  A pool of 20 gives comfortable headroom.
    DB_POOL_SIZE: int    = int(os.getenv("DB_POOL_SIZE", "20"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))

    # ── Authentication ────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str        = os.getenv("JWT_SECRET_KEY", "CHANGE_THIS_IN_PRODUCTION")
    JWT_ALGORITHM: str         = "HS256"
    JWT_EXPIRATION_HOURS: int  = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

    AGENT_TOKEN_EXPIRATION_DAYS: Optional[int] = None   # None = no expiry

    # ── Rate limiting (per-process; use Redis in production for multi-worker) ─
    LOGIN_RATE_LIMIT:  int = int(os.getenv("LOGIN_RATE_LIMIT",  "5"))
    LOGIN_RATE_WINDOW: int = int(os.getenv("LOGIN_RATE_WINDOW", "900"))

    # ── Energy calculation ────────────────────────────────────────────────────
    IDLE_POWER_WATTS:         float = float(os.getenv("IDLE_POWER_WATTS",         "65"))
    ACTIVE_POWER_WATTS:       float = float(os.getenv("ACTIVE_POWER_WATTS",       "120"))
    ELECTRICITY_COST_PER_KWH: float = float(os.getenv("ELECTRICITY_COST_PER_KWH", "0.12"))

    # ── Heartbeat / machine status ────────────────────────────────────────────
    HEARTBEAT_TIMEOUT_SECONDS:       int = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS",       "180"))
    IDLE_THRESHOLD_SECONDS:          int = int(os.getenv("IDLE_THRESHOLD_SECONDS",          "300"))
    OFFLINE_CHECK_INTERVAL_SECONDS:  int = int(os.getenv("OFFLINE_CHECK_INTERVAL_SECONDS",  "60"))

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Default log path uses the process working directory so the code works
    # both inside Docker (/app/logs/…) and in local development (./logs/…).
    # The logging setup in server/main.py creates the directory if needed.
    LOG_FILE: str = os.getenv(
        "LOG_FILE",
        os.path.join(os.getcwd(), "logs", "greenops.log"),
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list = os.getenv("CORS_ORIGINS", "*").split(",")

    # ── Initial admin password ────────────────────────────────────────────────
    # Set this env var on first boot to replace the default hash from the
    # migration.  The server applies it at startup then clears it from memory.
    # Remove from the environment after the first successful deployment.
    ADMIN_INITIAL_PASSWORD: Optional[str] = os.getenv("ADMIN_INITIAL_PASSWORD")

    # ── Validation ────────────────────────────────────────────────────────────
    @classmethod
    def validate(cls) -> None:
        if not cls.DATABASE_URL:
            raise ValueError("DATABASE_URL must be set.")

        if cls.JWT_SECRET_KEY == "CHANGE_THIS_IN_PRODUCTION":
            if not cls.DEBUG:
                raise ValueError(
                    "JWT_SECRET_KEY must be changed from the default value in "
                    "production.  Generate one with:\n"
                    "  python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "SECURITY WARNING: using default JWT_SECRET_KEY. "
                "Acceptable only in local development (DEBUG=true)."
            )


config = Config()

"""
GreenOps Server Configuration
==============================
All settings read from environment variables with safe defaults.
Call config.validate() at startup to fail fast on misconfiguration.

Local dev: export vars or create .env in project root.
Docker:    env_file: .env in docker-compose.yml.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional


# Resolve the project root relative to this file so LOG_FILE default
# works regardless of the current working directory.
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


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
    # Connection pool size.  With 4 workers × 2 threads = 8 concurrent users.
    # 10 gives comfortable headroom without exhausting PG max_connections.
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "10"))

    # ── Authentication ────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str       = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str        = "HS256"
    JWT_EXPIRATION_HOURS: int = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

    # ── Rate limiting ─────────────────────────────────────────────────────────
    LOGIN_RATE_LIMIT:  int = int(os.getenv("LOGIN_RATE_LIMIT",  "5"))
    LOGIN_RATE_WINDOW: int = int(os.getenv("LOGIN_RATE_WINDOW", "900"))

    # ── Energy calculation ────────────────────────────────────────────────────
    IDLE_POWER_WATTS:         float = float(os.getenv("IDLE_POWER_WATTS",         "65"))
    ACTIVE_POWER_WATTS:       float = float(os.getenv("ACTIVE_POWER_WATTS",       "120"))
    ELECTRICITY_COST_PER_KWH: float = float(os.getenv("ELECTRICITY_COST_PER_KWH", "0.12"))

    # ── Heartbeat / machine status ────────────────────────────────────────────
    HEARTBEAT_TIMEOUT_SECONDS:      int = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS",      "180"))
    IDLE_THRESHOLD_SECONDS:         int = int(os.getenv("IDLE_THRESHOLD_SECONDS",         "300"))
    OFFLINE_CHECK_INTERVAL_SECONDS: int = int(os.getenv("OFFLINE_CHECK_INTERVAL_SECONDS", "60"))

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Use __file__-relative default so the path is stable regardless of cwd.
    LOG_FILE: str = os.getenv(
        "LOG_FILE",
        str(_PROJECT_ROOT / "logs" / "greenops.log"),
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins.  Use "*" for dev only.
    CORS_ORIGINS: list = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "*").split(",")
        if o.strip()
    ]

    # ── Initial admin password ────────────────────────────────────────────────
    # Set on first boot to override the migration default hash.
    # Cleared from memory after first use. Do not set in production after
    # the first deployment.
    ADMIN_INITIAL_PASSWORD: Optional[str] = os.getenv("ADMIN_INITIAL_PASSWORD")

    # ── Validation ────────────────────────────────────────────────────────────

    @classmethod
    def validate(cls) -> None:
        """
        Strict configuration validation.
        Raises ValueError listing ALL problems found (not just the first).
        Call this at application startup — fail fast is safer than broken runtime.
        """
        errors: list[str] = []

        if not cls.DATABASE_URL:
            errors.append(
                "DATABASE_URL is not set. "
                "Example: postgresql://user:pass@host:5432/dbname"
            )

        if not cls.JWT_SECRET_KEY:
            errors.append(
                "JWT_SECRET_KEY is not set. "
                "Generate with: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        elif len(cls.JWT_SECRET_KEY) < 32:
            if not cls.DEBUG:
                errors.append(
                    f"JWT_SECRET_KEY is too short ({len(cls.JWT_SECRET_KEY)} chars). "
                    "Use at least 32 characters in production."
                )
            else:
                logging.getLogger(__name__).warning(
                    f"JWT_SECRET_KEY is short ({len(cls.JWT_SECRET_KEY)} chars). "
                    "Acceptable in DEBUG mode only."
                )

        if cls.DB_POOL_SIZE < 1 or cls.DB_POOL_SIZE > 100:
            errors.append(
                f"DB_POOL_SIZE={cls.DB_POOL_SIZE} is outside valid range [1, 100]."
            )

        if cls.JWT_EXPIRATION_HOURS < 1:
            errors.append("JWT_EXPIRATION_HOURS must be >= 1.")

        if errors:
            raise ValueError(
                "GreenOps configuration errors:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )


config = Config()

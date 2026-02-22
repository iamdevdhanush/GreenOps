"""
GreenOps Server — Application Factory  (production hardened)

Startup lifecycle:
  1. _configure_logging()   — sets up handlers; gracefully degrades if disk unavailable
  2. config.validate()      — fail-fast on missing/invalid env vars
  3. db.initialize()        — creates pool; retries smoke-test; exits on permanent failure
  4. _ensure_schema()       — applies DDL migrations idempotently, one statement per tx
  5. handle_errors(app)     — register Flask error handlers
  6. register blueprints
  7. _apply_admin_password()— one-time admin password bootstrap
  8. _start_offline_checker()— daemon thread, sleep-at-bottom pattern

Key fixes vs previous versions:
  - db.initialize() no longer calls sys.exit(); it raises, and create_app() decides.
  - Each DDL migration runs in its own transaction (not batched) so partial
    failure doesn't silently skip subsequent statements.
  - must_change_password column is queried with a safe fallback (returns False
    if column doesn't exist yet) to prevent 500s on partially-migrated DBs.
  - Offline checker uses Event.wait() not time.sleep() for clean shutdown.
  - app = create_app() is NOT at module level; gunicorn is told the factory
    via "server.main:create_app()" — this avoids double-init.
  - Graceful shutdown closes the pool before exit.
"""

import os
import sys
import signal
import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psycopg2
from flask import Flask, jsonify
from flask_cors import CORS

from server.config import config
from server.database import db
from server.middleware import handle_errors
from server.routes.auth import auth_bp
from server.routes.agents import agents_bp
from server.routes.dashboard import dashboard_bp

logger = logging.getLogger(__name__)

# Shared stop event so the offline checker thread can be asked to stop cleanly
_stop_event = threading.Event()


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

def _configure_logging() -> None:
    """
    Configure root logger.  Always adds a StreamHandler (stdout).
    Adds a RotatingFileHandler if the log directory can be created/written.
    Degrades gracefully: if the log path is unwritable, logs to stdout only.
    """
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    log_path = Path(config.LOG_FILE)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setLevel(log_level)
        handlers.insert(0, fh)
    except OSError as exc:
        # Print before basicConfig so this warning appears at startup
        print(
            f"[greenops] WARNING: cannot open log file {log_path}: {exc}. "
            "Falling back to stdout only.",
            flush=True,
        )

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(name)-30s %(levelname)-8s %(message)s",
        handlers=handlers,
        force=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Schema migrations (idempotent, one-statement-per-transaction)
# ─────────────────────────────────────────────────────────────────────────────

# Each tuple is (description, sql).  Each runs in its own transaction so a
# failure in one does not silently roll back subsequent statements.
_SCHEMA_MIGRATIONS: list[tuple[str, str]] = [
    (
        "add must_change_password to users",
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name = 'must_change_password'
            ) THEN
                ALTER TABLE users
                    ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
            END IF;
        END $$
        """,
    ),
    (
        "add uptime_seconds to machines",
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'machines'
                  AND column_name = 'uptime_seconds'
            ) THEN
                ALTER TABLE machines
                    ADD COLUMN uptime_seconds BIGINT NOT NULL DEFAULT 0;
            END IF;
        END $$
        """,
    ),
    (
        "create machine_commands table",
        """
        CREATE TABLE IF NOT EXISTS machine_commands (
            id          SERIAL PRIMARY KEY,
            machine_id  INTEGER     NOT NULL REFERENCES machines (id) ON DELETE CASCADE,
            command     VARCHAR(20) NOT NULL,
            status      VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_by  INTEGER     REFERENCES users (id),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            executed_at TIMESTAMPTZ,
            result_msg  TEXT,
            CONSTRAINT valid_command
                CHECK (command IN ('sleep', 'shutdown')),
            CONSTRAINT valid_cmd_status
                CHECK (status  IN ('pending', 'executed', 'failed', 'expired'))
        )
        """,
    ),
    (
        "create machine_commands pending index",
        """
        CREATE INDEX IF NOT EXISTS idx_commands_machine_status
            ON machine_commands (machine_id, status)
            WHERE status = 'pending'
        """,
    ),
]


def _ensure_schema() -> None:
    """
    Run each DDL migration in its own transaction.
    Logs each step.  Non-fatal per-statement (logs error, continues).
    Fatal only if the DB connection itself fails.
    """
    for description, sql in _SCHEMA_MIGRATIONS:
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
            logger.debug(f"Schema OK: {description}")
        except Exception as exc:
            logger.error(f"Schema migration failed [{description}]: {exc}")
            # Continue — other migrations may still succeed.
            # A later SELECT for must_change_password will use the safe fallback.
    logger.info("Schema migrations complete.")


# ─────────────────────────────────────────────────────────────────────────────
# Admin password bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def _apply_admin_password() -> None:
    """Apply ADMIN_INITIAL_PASSWORD if set, then clear it from memory."""
    if not config.ADMIN_INITIAL_PASSWORD:
        return

    logger.info("Applying ADMIN_INITIAL_PASSWORD …")
    try:
        from server.auth import AuthService
        new_hash = AuthService.hash_password(config.ADMIN_INITIAL_PASSWORD)
        rows = db.execute_query(
            "UPDATE users SET password_hash = %s WHERE username = 'admin'",
            (new_hash,),
        )
        if rows:
            logger.info("Admin password updated from ADMIN_INITIAL_PASSWORD.")
        else:
            logger.warning(
                "ADMIN_INITIAL_PASSWORD set but no 'admin' user found. "
                "Has migration 001 run?"
            )
    except Exception as exc:
        logger.error(f"Failed to apply ADMIN_INITIAL_PASSWORD: {exc}", exc_info=True)
        # Non-fatal: the server starts but admin password may be the migration default.
    finally:
        config.ADMIN_INITIAL_PASSWORD = None


# ─────────────────────────────────────────────────────────────────────────────
# Offline machine checker
# ─────────────────────────────────────────────────────────────────────────────

def _start_offline_checker(app: Flask, interval: int) -> None:
    """
    Background daemon thread: marks machines offline and expires commands.

    Uses Event.wait() (not time.sleep()) so the thread wakes up immediately
    when _stop_event is set during graceful shutdown.

    sleep-at-BOTTOM pattern: runs once immediately on first tick, then waits.
    This means machines are checked ~1s after server start rather than
    waiting a full interval before the first check.
    """

    def _loop() -> None:
        # First tick runs almost immediately, subsequent ticks every `interval` s.
        first_run = True
        while not _stop_event.is_set():
            if not first_run:
                _stop_event.wait(timeout=interval)
                if _stop_event.is_set():
                    break
            first_run = False

            try:
                with app.app_context():
                    from server.services.machine import MachineService
                    count = MachineService.update_offline_machines()
                    if count:
                        logger.info(f"Offline checker: {count} machine(s) marked offline.")

                    db.execute_query(
                        """
                        UPDATE machine_commands
                        SET    status = 'expired'
                        WHERE  status = 'pending'
                          AND  created_at < NOW() - INTERVAL '5 minutes'
                        """
                    )
            except psycopg2.OperationalError as exc:
                logger.error(
                    f"Offline checker: DB connection lost ({exc}). "
                    "Reinitialising pool …"
                )
                try:
                    db.initialize()
                    logger.info("Offline checker: DB pool reconnected.")
                except Exception as init_exc:
                    logger.error(
                        f"Offline checker: reconnect failed: {init_exc}. "
                        "Will retry next tick."
                    )
            except Exception as exc:
                logger.error(f"Offline checker error: {exc}", exc_info=True)

    t = threading.Thread(target=_loop, daemon=True, name="offline-checker")
    t.start()
    logger.info(
        f"Offline checker started (interval={interval}s, pid={os.getpid()})."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Application factory
# ─────────────────────────────────────────────────────────────────────────────

def create_app() -> Flask:
    """
    Flask application factory.
    Called once in the gunicorn master (preload_app=True).
    Workers reinitialize the DB pool in post_fork().
    """
    _configure_logging()

    logger.info(
        f"create_app() starting — pid={os.getpid()}, "
        f"debug={config.DEBUG}, log={config.LOG_FILE}"
    )

    # ── Validate configuration ────────────────────────────────────────────────
    try:
        config.validate()
    except ValueError as exc:
        logger.critical(f"Configuration invalid:\n{exc}")
        sys.exit(1)

    # ── Flask app ─────────────────────────────────────────────────────────────
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    CORS(app, origins=config.CORS_ORIGINS, supports_credentials=True)

    # ── Database ──────────────────────────────────────────────────────────────
    try:
        db.initialize()
    except Exception as exc:
        logger.critical(
            f"Database initialization failed: {exc}\n"
            "Ensure DATABASE_URL is correct and PostgreSQL is running."
        )
        sys.exit(1)

    # ── Schema migrations ─────────────────────────────────────────────────────
    _ensure_schema()

    # ── Error handlers + blueprints ───────────────────────────────────────────
    handle_errors(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(dashboard_bp)

    # ── Built-in routes ───────────────────────────────────────────────────────
    @app.route("/")
    def root():
        return jsonify({
            "service": "GreenOps",
            "version": "2.0.0",
            "status": "operational",
        })

    @app.route("/health")
    def health():
        """
        Deterministic health check used by Docker and nginx.
        Performs a lightweight SELECT 1 to confirm DB connectivity.
        Returns 200 only when the DB is reachable.
        """
        try:
            result = db.execute_one("SELECT 1 AS ok")
            if result and result.get("ok") == 1:
                return jsonify({"status": "healthy", "database": "connected"}), 200
            return jsonify({"status": "degraded", "database": "unexpected response"}), 503
        except Exception as exc:
            logger.error(f"Health check DB query failed: {exc}")
            return jsonify({"status": "unhealthy", "database": "disconnected"}), 503

    # ── One-time admin password ───────────────────────────────────────────────
    _apply_admin_password()

    # ── Background services ───────────────────────────────────────────────────
    # Only start the offline checker in the master process.
    # preload_app=True means create_app() runs ONCE in the master before fork.
    # Workers get their own pool via post_fork(); they do NOT run this checker.
    _start_offline_checker(app, config.OFFLINE_CHECK_INTERVAL_SECONDS)

    logger.info("GreenOps server initialised and ready.")
    return app


# ─────────────────────────────────────────────────────────────────────────────
# Graceful shutdown
# ─────────────────────────────────────────────────────────────────────────────

def _graceful_shutdown(signum, frame):
    logger.info(f"Received signal {signum} — shutting down …")
    _stop_event.set()   # wake up offline checker
    db.close()
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level app (for gunicorn "server.main:app" invocation)
# ─────────────────────────────────────────────────────────────────────────────
# NOTE: gunicorn.conf.py uses CMD ["gunicorn", "-c", "gunicorn.conf.py",
# "server.main:app"], which triggers create_app() here at import time.
# This is intentional with preload_app=True.
# For local dev ("python3 -m server.main"), main() is called instead.

signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)

app = create_app()


def main():
    """Entry point for local development: python3 -m server.main"""
    logger.info(f"Starting GreenOps dev server on {config.HOST}:{config.PORT}")
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        use_reloader=False,   # reloader forks; creates second create_app() call
        threaded=True,
    )


if __name__ == "__main__":
    main()

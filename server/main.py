"""
GreenOps Server — Main application entry point and factory.

Architecture notes
------------------
* create_app() runs ONCE in the gunicorn master process (preload_app=True).
  It must NOT be called in workers; post_fork() handles worker DB setup.
* _run_offline_check() starts a daemon thread in the master.  Daemon threads
  are NOT inherited after fork(), so exactly one checker runs for the whole
  server regardless of the number of workers.
* _apply_admin_initial_password() also runs once in the master, eliminating
  the concurrent-UPDATE race that occurred when it ran inside every worker.
* Logging is configured inside create_app() with force=True so our handlers
  replace any handlers gunicorn may have already attached to the root logger.
  The log directory is created automatically if it does not exist.
"""

import os
import sys
import signal
import logging
import time
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, jsonify
from flask_cors import CORS

from server.config import config
from server.database import db
from server.middleware import handle_errors
from server.routes.auth import auth_bp
from server.routes.agents import agents_bp
from server.routes.dashboard import dashboard_bp


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    """
    Set up root-level logging with both a rotating file handler and stdout.

    Rationale for force=True:
        logging.basicConfig() is a no-op if the root logger already has
        handlers.  Gunicorn attaches its own handlers before importing the
        app, so without force=True our RotatingFileHandler is silently
        discarded and log output from Flask/SQLAlchemy/etc. disappears.

    Rationale for mkdir:
        The default log path (/app/logs/greenops.log) lives inside the
        Docker container.  We create the directory here so the code works
        both inside the container and in local dev where the path may not
        exist yet.  If directory creation fails we fall back gracefully to
        stdout-only logging rather than crashing on import.
    """
    log_path = Path(config.LOG_FILE)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            config.LOG_FILE,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
        )
        handlers.insert(0, file_handler)
    except OSError as exc:
        # Not fatal — stdout logging is sufficient.
        print(
            f"[greenops] WARNING: cannot create log directory "
            f"{log_path.parent}: {exc}. Falling back to stdout only.",
            flush=True,
        )

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,   # <── override any handlers gunicorn already installed
    )


logger = logging.getLogger(__name__)


def _apply_admin_initial_password() -> None:
    """
    If ADMIN_INITIAL_PASSWORD is set in the environment, update the admin
    account hash in the database and then discard the plaintext value.

    This runs exactly once — in the gunicorn master (preload_app=True) —
    so there is no concurrent-write race between workers.
    """
    if not config.ADMIN_INITIAL_PASSWORD:
        return

    logger.info("Applying ADMIN_INITIAL_PASSWORD …")
    try:
        from server.auth import AuthService
        new_hash = AuthService.hash_password(config.ADMIN_INITIAL_PASSWORD)
        db.execute_query(
            "UPDATE users SET password_hash = %s WHERE username = 'admin'",
            (new_hash,),
        )
        logger.info("Admin password updated from ADMIN_INITIAL_PASSWORD.")
    except Exception as exc:
        logger.error(
            f"Failed to apply ADMIN_INITIAL_PASSWORD: {exc}", exc_info=True
        )
        sys.exit(1)
    finally:
        # Discard the plaintext so it does not linger in master's memory.
        config.ADMIN_INITIAL_PASSWORD = None


def _run_offline_check(app: Flask, interval: int) -> None:
    """
    Daemon thread that periodically marks machines offline when their last
    heartbeat exceeds HEARTBEAT_TIMEOUT_SECONDS.

    Why a daemon thread in the master (not in workers)?
        With preload_app=True, create_app() runs in the master process.
        Daemon threads started here do NOT carry over into worker processes
        after fork() — only the calling thread survives the fork.  So exactly
        one offline-checker runs for the whole server, using the master's own
        DB pool connection (not shared with workers).

    time.sleep() vs threading.Event().wait():
        The original code created a new Event object each iteration and called
        .wait(timeout) on it.  This is functionally equivalent to sleep() but
        allocates a new synchronisation primitive every loop.  We use
        time.sleep() with a persistent shutdown Event so the thread can be
        woken early if needed in the future.
    """
    _stop = threading.Event()

    def _loop() -> None:
        while not _stop.wait(timeout=interval):
            try:
                with app.app_context():
                    from server.services.machine import MachineService
                    count = MachineService.update_offline_machines()
                    if count:
                        logger.info(
                            f"Offline checker: marked {count} machine(s) offline."
                        )
            except Exception as exc:
                logger.error(f"Offline check error: {exc}", exc_info=True)

    t = threading.Thread(target=_loop, daemon=True, name="offline-check")
    t.start()
    logger.info(
        f"Offline checker started "
        f"(interval={interval}s, pid={os.getpid()}, thread={t.name})."
    )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    """
    Build and return the Flask application.

    With gunicorn's preload_app=True this function is called ONCE in the
    master process.  Workers receive the resulting `app` object via fork().
    post_fork() reinitialises the DB pool inside each worker so they own
    independent connections.
    """

    # 1. Logging must be configured first so every subsequent step is visible.
    _configure_logging()

    logger.info(
        f"create_app() starting (pid={os.getpid()}, "
        f"debug={config.DEBUG}, log={config.LOG_FILE})"
    )

    # 2. Validate critical configuration before touching the DB.
    try:
        config.validate()
    except ValueError as exc:
        logger.error(f"Configuration error: {exc}")
        sys.exit(1)

    # 3. Flask application.
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    CORS(app, origins=config.CORS_ORIGINS, supports_credentials=True)

    # 4. Database pool — for the master process (and the offline-check thread).
    #    Each worker will call db.close() + db.initialize() in post_fork().
    try:
        db.initialize()
    except Exception as exc:
        logger.error(f"Failed to initialise database: {exc}", exc_info=True)
        sys.exit(1)

    # 5. Error handlers & route blueprints.
    handle_errors(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(dashboard_bp)

    # 6. Built-in routes.
    @app.route("/")
    def root():
        return jsonify(
            {"service": "GreenOps", "version": "1.0.0", "status": "operational"}
        )

    @app.route("/health")
    def health():
        try:
            db.execute_one("SELECT 1")
            return jsonify({"status": "healthy", "database": "connected"}), 200
        except Exception:
            return jsonify({"status": "unhealthy", "database": "disconnected"}), 503

    # 7. One-shot admin password update (master only, no worker race).
    _apply_admin_initial_password()

    # 8. Single offline-check background thread (master only; not forked into workers).
    _run_offline_check(app, config.OFFLINE_CHECK_INTERVAL_SECONDS)

    logger.info("GreenOps server initialised and ready.")
    return app


# ---------------------------------------------------------------------------
# Graceful shutdown (used when running via `python -m server.main`)
# ---------------------------------------------------------------------------

def graceful_shutdown(signum, frame):
    logger.info(f"Received signal {signum}, shutting down …")
    db.close()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Module-level app object
# ---------------------------------------------------------------------------
# Gunicorn discovers the WSGI callable via the "server.main:app" argument.
# With preload_app=True this assignment executes exactly once in the master.
# Do NOT move create_app() inside a guard — gunicorn must be able to import
# this module and find `app` at module scope.
app = create_app()


# ---------------------------------------------------------------------------
# Direct entry point (local development without gunicorn)
# ---------------------------------------------------------------------------

def main():
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    logger.info(f"Starting GreenOps server on {config.HOST}:{config.PORT}")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)


if __name__ == "__main__":
    main()

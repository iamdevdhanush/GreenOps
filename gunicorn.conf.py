"""
GreenOps Gunicorn Configuration — Production

Worker model: gthread (threaded), 4 workers × 2 threads = 8 concurrent.
preload_app=True: app imported ONCE in master, workers fork.
  - create_app() runs once → DB pool, schema migration, admin password,
    offline checker all happen in master.
  - post_fork() replaces the inherited (shared) pool with a worker-owned one.
  - worker_exit() cleans up the worker's pool on exit.

Timeout: 30s per-worker (industry standard). Adjust up only if you have
genuinely long-running endpoints (e.g., bulk export).
"""

import os
import sys
import time

# ── Bind ──────────────────────────────────────────────────────────────────────
bind = "0.0.0.0:8000"

# ── Workers ───────────────────────────────────────────────────────────────────
workers      = 4
worker_class = "gthread"
threads      = 2
timeout      = 30       # 30s is industry standard; was 120 (too long)
keepalive    = 5
graceful_timeout = 30

# ── App loading ───────────────────────────────────────────────────────────────
preload_app = True

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog     = "-"     # stdout (captured by Docker / systemd)
errorlog      = "-"     # stdout
loglevel      = "info"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sus'

# ── Process naming ────────────────────────────────────────────────────────────
proc_name = "greenops"


# ── Hooks ─────────────────────────────────────────────────────────────────────

def on_starting(server):
    """
    Master process: wait for PostgreSQL before loading the app.
    The app's create_app() → db.initialize() will also verify connectivity,
    but we do an early check here so the master never even attempts to import
    the app if the DB isn't up yet, preventing a confusing ImportError-style
    crash chain.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("[gunicorn] FATAL: DATABASE_URL not set.", flush=True)
        sys.exit(1)

    try:
        import psycopg2
    except ImportError:
        print("[gunicorn] FATAL: psycopg2 not installed.", flush=True)
        sys.exit(1)

    print("[gunicorn] Waiting for PostgreSQL …", flush=True)
    for attempt in range(1, 31):          # up to 60 s
        try:
            conn = psycopg2.connect(db_url, connect_timeout=3)
            conn.close()
            print(
                f"[gunicorn] PostgreSQL ready (attempt {attempt}).",
                flush=True,
            )
            return
        except psycopg2.OperationalError as exc:
            print(
                f"[gunicorn] Waiting … attempt {attempt}/30: {exc}",
                flush=True,
            )
            time.sleep(2)

    print("[gunicorn] FATAL: PostgreSQL never became ready.", flush=True)
    sys.exit(1)


def post_fork(server, worker):
    """
    Worker process: replace inherited master pool with a fresh worker pool.
    The master's pool file descriptors are shared at the OS level after fork.
    Closing them here (in the worker's address space) does NOT affect the
    master's pool — they are separate memory spaces after fork.
    """
    from server.database import db

    try:
        db.close()       # release inherited (shared) sockets
    except Exception:
        pass

    try:
        db.initialize()  # fresh pool owned by this worker
    except Exception as exc:
        print(f"[gunicorn] Worker {worker.pid}: DB init failed: {exc}", flush=True)
        # Don't sys.exit() here — gunicorn will detect the worker is broken
        # and restart it. Exiting would cause an immediate respawn loop.

    print(f"[gunicorn] Worker {worker.pid}: ready.", flush=True)


def worker_exit(server, worker):
    """Worker process exiting: close DB pool cleanly."""
    try:
        from server.database import db
        db.close()
    except Exception:
        pass

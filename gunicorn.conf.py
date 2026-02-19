"""
GreenOps Gunicorn Configuration
================================
Key design decision: preload_app = True
  - The WSGI app (server.main:app) is imported ONCE in the master process.
  - create_app() → db.initialize() runs exactly once (no double-init).
  - Background threads started in create_app() live in the master only;
    they are NOT duplicated into workers after fork().
  - post_fork() closes the inherited (shared) DB sockets and opens fresh
    connections owned solely by the new worker process.

Lifecycle with preload_app = True:
  1. on_starting()   – master: wait for PostgreSQL to accept connections
  2. App preloaded   – master: import server.main, run create_app()
                       db.initialize() / _run_offline_check() happen here
  3. Workers forked  – each worker is a copy of master memory
  4. post_fork()     – each worker: close shared sockets, open fresh pool
  5. Workers serve   – each worker owns its own independent connection pool
"""

import os
import sys
import time

# ── Server socket ─────────────────────────────────────────────────────────────
bind = "0.0.0.0:8000"

# ── Workers ───────────────────────────────────────────────────────────────────
# gthread: one process per worker, multiple threads sharing one DB pool.
# The pool size in server/config.py (default 20) should be >= threads * workers.
workers = 4
worker_class = "gthread"
threads = 2
timeout = 120
keepalive = 5

# ── CRITICAL: load the app once in the master before forking ──────────────────
# Setting this to False (the default) causes each worker to call create_app()
# independently, which leads to double db.initialize() calls, leaked connection
# pools, and eventual PostgreSQL connection exhaustion.
preload_app = True


# ── Hooks ─────────────────────────────────────────────────────────────────────

def on_starting(server):
    """
    Runs in the master process BEFORE the app is loaded.

    We wait here for PostgreSQL to accept connections so that db.initialize()
    inside create_app() succeeds on the first attempt rather than calling
    sys.exit(1) and triggering a Docker restart loop.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print(
            "[gunicorn] FATAL: DATABASE_URL is not set. Cannot start.",
            flush=True,
        )
        sys.exit(1)

    print("[gunicorn] Waiting for PostgreSQL …", flush=True)

    try:
        import psycopg2
    except ImportError:
        print("[gunicorn] FATAL: psycopg2 is not installed.", flush=True)
        sys.exit(1)

    for attempt in range(1, 31):          # up to ~60 s (30 × 2 s)
        try:
            conn = psycopg2.connect(db_url, connect_timeout=3)
            conn.close()
            print(
                f"[gunicorn] PostgreSQL is ready (attempt {attempt}).",
                flush=True,
            )
            return
        except psycopg2.OperationalError as exc:
            print(
                f"[gunicorn] DB not ready yet (attempt {attempt}/30): {exc}",
                flush=True,
            )
            time.sleep(2)

    print("[gunicorn] FATAL: PostgreSQL never became ready. Exiting.", flush=True)
    sys.exit(1)


def post_fork(server, worker):
    """
    Runs inside each worker immediately after fork().

    After fork() the worker inherits the master's open DB file descriptors.
    Those sockets are now shared between master and worker at the OS level,
    which is unsafe for psycopg2 connections.  We:
      1. Close the inherited pool (releases the shared file descriptors in
         this worker's address space without touching the master's copy).
      2. Open a brand-new pool with connections owned exclusively by this worker.

    This is the ONLY place db.initialize() should be called for workers.
    create_app() initialises the pool for the master; post_fork() replaces it
    for each worker.
    """
    from server.database import db

    try:
        db.close()          # discard inherited (shared) connections
    except Exception:
        pass                # pool may not exist yet on very first worker

    db.initialize()         # fresh connections owned by this worker

    print(
        f"[gunicorn] Worker {worker.pid}: DB pool initialised.",
        flush=True,
    )

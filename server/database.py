"""
GreenOps Database Layer — Production Hardened
=============================================

Design decisions:
  minconn=1  — psycopg2 requires minconn >= 1. Using 0 causes PoolError under
               load ("connection pool exhausted") because no slots are allocated.
               One persistent connection is acceptable; keepalives prevent it
               from going stale.

  keepalives — TCP keepalives fire every 30s, preventing Docker NAT from
               silently dropping idle connections.

  retry      — initialize() retries the smoke-test connection up to 3 times
               with a short backoff rather than calling sys.exit() immediately.
               This handles the race where gunicorn's on_starting() completes
               just before PostgreSQL finishes initializing schema on first boot.

  pool exhaustion — get_connection() raises a clear RuntimeError with context
               instead of letting psycopg2 raise an opaque PoolError that
               becomes a 500 with no diagnostic info.
"""

import logging
import threading
import time
from contextlib import contextmanager
from typing import Optional

import psycopg2
from psycopg2 import pool, extras

from server.config import config

logger = logging.getLogger(__name__)

_KEEPALIVE_KWARGS = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}

# How many times to retry the smoke-test SELECT 1 on pool initialization
_INIT_RETRIES = 3
_INIT_RETRY_DELAY = 2.0  # seconds


class Database:
    """Thread-safe PostgreSQL connection pool manager."""

    def __init__(self):
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._lock = threading.Lock()

    @property
    def pool(self) -> Optional[pool.ThreadedConnectionPool]:
        return self._pool

    def initialize(self) -> None:
        """
        Create a new connection pool and verify connectivity.
        Thread-safe. Safe to call in post_fork() workers.
        Retries the smoke-test to handle slow DB initialization.
        Raises on failure (caller decides whether to sys.exit or retry).
        """
        with self._lock:
            # Close any existing pool first (safe in post_fork workers)
            if self._pool is not None:
                try:
                    self._pool.closeall()
                    logger.debug("Existing DB pool closed before re-init.")
                except Exception as exc:
                    logger.warning(f"Error closing existing pool: {exc}")
                self._pool = None

            try:
                self._pool = pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=config.DB_POOL_SIZE,
                    dsn=config.DATABASE_URL,
                    **_KEEPALIVE_KWARGS,
                )
                logger.info(
                    f"Database pool created "
                    f"(minconn=1, maxconn={config.DB_POOL_SIZE}, keepalives=on)."
                )
            except psycopg2.OperationalError as exc:
                logger.error(f"Failed to create DB pool: {exc}")
                raise
            except Exception as exc:
                logger.error(f"Unexpected error creating DB pool: {exc}")
                raise

        # Smoke-test outside the lock (get_connection acquires lock internally
        # via pool, not our _lock)
        last_exc = None
        for attempt in range(1, _INIT_RETRIES + 1):
            try:
                with self.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                logger.info("Database connectivity verified.")
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    f"DB smoke-test attempt {attempt}/{_INIT_RETRIES} failed: {exc}"
                )
                if attempt < _INIT_RETRIES:
                    time.sleep(_INIT_RETRY_DELAY)

        logger.error(f"DB smoke-test failed after {_INIT_RETRIES} attempts: {last_exc}")
        raise last_exc

    @contextmanager
    def get_connection(self):
        """
        Yield a checked-out connection.  Commits on success, rolls back on
        exception, always returns the connection to the pool.

        Raises RuntimeError if the pool is not initialised.
        Raises psycopg2.pool.PoolError (with a clear message) if exhausted.
        """
        if self._pool is None:
            raise RuntimeError(
                "Database pool is not initialised. "
                "Call db.initialize() before making requests."
            )

        conn = None
        try:
            conn = self._pool.getconn()
            if conn is None:
                raise RuntimeError("Pool returned None — pool exhausted or closed.")
            yield conn
            conn.commit()
        except psycopg2.pool.PoolError as exc:
            raise RuntimeError(
                f"DB connection pool exhausted (maxconn={config.DB_POOL_SIZE}). "
                f"Consider increasing DB_POOL_SIZE. Original: {exc}"
            ) from exc
        except Exception as exc:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"Database error: {exc}")
            raise
        finally:
            if conn is not None and self._pool is not None:
                try:
                    self._pool.putconn(conn)
                except Exception:
                    pass  # pool may have been closed during shutdown

    def execute_query(
        self, query: str, params: tuple = None, fetch: bool = False
    ):
        """Execute a query. Returns rowcount or list of RealDictRows."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, params)
                if fetch:
                    return cur.fetchall()
                return cur.rowcount

    def execute_one(self, query: str, params: tuple = None):
        """Execute a query and return the first row as a RealDictRow."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, params)
                return cur.fetchone()

    def close(self) -> None:
        """Close all connections in the pool. Safe to call multiple times."""
        with self._lock:
            if self._pool is not None:
                try:
                    self._pool.closeall()
                    logger.info("Database pool closed.")
                except Exception as exc:
                    logger.warning(f"Error during pool close: {exc}")
                self._pool = None


db = Database()

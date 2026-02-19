"""
GreenOps Database Layer
=======================
Connection pooling, context management, and graceful shutdown.

The single most important invariant: initialize() is safe to call multiple
times (e.g. in post_fork()).  It always closes the existing pool first to
avoid leaking file descriptors and PostgreSQL server-side connections.
"""

import logging
import threading
from contextlib import contextmanager
from typing import Optional

import psycopg2
from psycopg2 import pool, extras

from server.config import config

logger = logging.getLogger(__name__)


class Database:
    """Thread-safe database connection pool manager."""

    def __init__(self):
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._lock = threading.Lock()

    @property
    def pool(self) -> Optional[pool.ThreadedConnectionPool]:
        return self._pool

    def initialize(self) -> None:
        """
        (Re-)initialise the connection pool.

        Why close first?
            After gunicorn forks a worker, that worker inherits the master's
            open DB sockets at the OS level.  If we simply create a new pool
            without closing the inherited one, the old socket file descriptors
            remain open in this process (leaking), and PostgreSQL keeps the
            corresponding server-side connections alive until they time out.
            Over multiple restarts this exhausts PostgreSQL's max_connections
            (default 100) and triggers the observed restart loop.

        Thread safety:
            A lock serialises concurrent initialize() calls that could arrive
            if (hypothetically) two threads call this at the same time.
        """
        with self._lock:
            # Close existing pool (inherited from master after fork, or from
            # a previous initialize() call) before creating a new one.
            if self._pool is not None:
                try:
                    self._pool.closeall()
                    logger.debug("Existing DB pool closed before reinitialisation.")
                except Exception as exc:
                    logger.warning(f"Error closing existing pool: {exc}")
                self._pool = None

            try:
                self._pool = pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=config.DB_POOL_SIZE,
                    dsn=config.DATABASE_URL,
                )
                logger.info(
                    f"Database pool initialised "
                    f"(minconn=1, maxconn={config.DB_POOL_SIZE})."
                )
            except Exception as exc:
                logger.error(f"Failed to create DB pool: {exc}")
                raise

            # Smoke-test: verify we can actually talk to the database.
            try:
                with self.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                logger.info("Database connectivity verified.")
            except Exception as exc:
                logger.error(f"DB smoke-test failed: {exc}")
                raise

    @contextmanager
    def get_connection(self):
        """
        Yield a connection from the pool, committing on success or rolling
        back on exception, and always returning the connection to the pool.
        """
        if self._pool is None:
            raise RuntimeError(
                "Database pool is not initialised. "
                "Call db.initialize() before using the database."
            )

        conn = None
        try:
            conn = self._pool.getconn()
            yield conn
            conn.commit()
        except Exception as exc:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"Database error: {exc}")
            raise
        finally:
            if conn is not None:
                self._pool.putconn(conn)

    def execute_query(
        self,
        query: str,
        params: tuple = None,
        fetch: bool = False,
    ):
        """Execute a query; optionally return all rows as RealDictRow objects."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, params)
                if fetch:
                    return cur.fetchall()
                return cur.rowcount

    def execute_one(self, query: str, params: tuple = None):
        """Execute a query and return a single RealDictRow (or None)."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, params)
                return cur.fetchone()

    def close(self) -> None:
        """Close all connections in the pool (e.g. on graceful shutdown)."""
        with self._lock:
            if self._pool is not None:
                try:
                    self._pool.closeall()
                    logger.info("Database pool closed.")
                except Exception as exc:
                    logger.warning(f"Error during pool close: {exc}")
                self._pool = None


# Singleton used throughout the server package.
db = Database()

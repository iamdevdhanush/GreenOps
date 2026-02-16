"""
GreenOps Database Layer
Connection pooling, context management, graceful shutdown
"""
import psycopg2
from psycopg2 import pool, extras
from contextlib import contextmanager
import logging
from typing import Optional
from server.config import config

logger = logging.getLogger(__name__)

class Database:
    """Database connection pool manager"""
    
    def __init__(self):
        self.pool: Optional[pool.ThreadedConnectionPool] = None
        
    def initialize(self):
        """Initialize connection pool"""
        try:
            self.pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=config.DB_POOL_SIZE,
                dsn=config.DATABASE_URL
            )
            logger.info(f"Database pool initialized (size: {config.DB_POOL_SIZE})")
            
            # Test connection
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    logger.info("Database connection verified")
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Get connection from pool with automatic return"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        
        conn = None
        try:
            conn = self.pool.getconn()
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                self.pool.putconn(conn)
    
    def execute_query(self, query: str, params: tuple = None, fetch: bool = False):
        """Execute query with automatic connection management"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, params)
                if fetch:
                    return cur.fetchall()
                return cur.rowcount
    
    def execute_one(self, query: str, params: tuple = None):
        """Execute query and return single result"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, params)
                return cur.fetchone()
    
    def close(self):
        """Close all connections gracefully"""
        if self.pool:
            self.pool.closeall()
            logger.info("Database pool closed")

# Global database instance
db = Database()

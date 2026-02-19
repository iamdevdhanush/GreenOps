"""
Gunicorn configuration for GreenOps server.
post_fork re-initialises the DB connection pool in each worker to avoid
inheriting file descriptors and semaphores from the master process across
the fork boundary (psycopg2 ThreadedConnectionPool is not fork-safe).
"""
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = int(os.getenv("GUNICORN_WORKERS", "4"))
worker_class = "gthread"
threads = int(os.getenv("GUNICORN_THREADS", "2"))
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()


def post_fork(server, worker):
    from server.database import db
    db.close()
    db.initialize()

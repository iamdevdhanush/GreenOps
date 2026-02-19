"""
GreenOps Middleware
JWT validation, agent token validation, rate limiting, error handling.

NOTE: The login rate limiter uses a per-process in-memory store. With multiple
Gunicorn workers each process maintains its own counter, so the effective limit
is LOGIN_RATE_LIMIT * num_workers. Replace with a Redis-backed store before
exposing this service to the public internet.
"""
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

from flask import g, jsonify, request

from server.auth import AuthService
from server.config import config

import logging

logger = logging.getLogger(__name__)

_login_attempts: dict = defaultdict(list)
_rate_limit_lock = threading.Lock()

_VALID_STATUSES = {"online", "idle", "offline"}


def require_jwt(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid authorization header"}), 401

        token = auth_header[len("Bearer "):]
        payload = AuthService.verify_jwt(token)
        if not payload:
            return jsonify({"error": "Invalid or expired token"}), 401

        g.user_id = payload["user_id"]
        g.username = payload["username"]
        g.role = payload["role"]
        return f(*args, **kwargs)

    return decorated


def require_admin(f):
    @wraps(f)
    @require_jwt
    def decorated(*args, **kwargs):
        if g.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated


def require_agent_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid authorization header"}), 401

        token = auth_header[len("Bearer "):]
        machine_id = AuthService.verify_agent_token(token)
        if not machine_id:
            return jsonify({"error": "Invalid agent token"}), 401

        g.machine_id = machine_id
        return f(*args, **kwargs)

    return decorated


def rate_limit_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=config.LOGIN_RATE_WINDOW)

        with _rate_limit_lock:
            _login_attempts[ip] = [t for t in _login_attempts[ip] if t > cutoff]
            if len(_login_attempts[ip]) >= config.LOGIN_RATE_LIMIT:
                logger.warning(f"Rate limit exceeded for IP: {ip}")
                return (
                    jsonify({"error": "Too many login attempts. Please try again later."}),
                    429,
                )
            _login_attempts[ip].append(now)

        return f(*args, **kwargs)

    return decorated


def validate_status_param(status: str) -> bool:
    return status in _VALID_STATUSES


def handle_errors(app: "Flask") -> None:
    @app.errorhandler(400)
    def bad_request(exc):
        return jsonify({"error": "Bad request", "detail": str(exc)}), 400

    @app.errorhandler(404)
    def not_found(exc):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(exc):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(500)
    def internal_error(exc):
        logger.error(f"Internal server error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(Exception)
    def handle_exception(exc):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

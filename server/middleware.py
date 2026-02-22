"""
GreenOps Middleware
====================
Decorators: require_jwt, require_admin, require_agent_token, rate_limit_login
Error handlers: 400, 404, 405, 429, 500, unhandled Exception
Security headers added to every response.
"""
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from typing import TYPE_CHECKING

from flask import Flask, g, jsonify, request

from server.auth import AuthService
from server.config import config

import logging

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Per-process in-memory rate limiter.
# With 4 gunicorn workers the effective limit is 4× configured value.
# For public-facing production, replace with a Redis-backed store.
_login_attempts: dict = defaultdict(list)
_rate_lock = threading.Lock()

_VALID_STATUSES = frozenset({"online", "idle", "offline"})


# ─────────────────────────────────────────────────────────────────────────────
# Auth decorators
# ─────────────────────────────────────────────────────────────────────────────

def require_jwt(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Authorization header missing or malformed"}), 401

        token = auth[len("Bearer "):]
        payload = AuthService.verify_jwt(token)
        if not payload:
            return jsonify({"error": "Invalid or expired token"}), 401

        g.user_id  = payload.get("user_id")
        g.username = payload.get("username", "")
        g.role     = payload.get("role", "viewer")

        if g.user_id is None:
            logger.error("JWT payload missing user_id field.")
            return jsonify({"error": "Malformed token"}), 401

        return f(*args, **kwargs)

    return decorated


def require_admin(f):
    """Requires a valid JWT AND admin role."""
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
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Authorization header missing or malformed"}), 401

        token = auth[len("Bearer "):]
        machine_id = AuthService.verify_agent_token(token)
        if not machine_id:
            return jsonify({"error": "Invalid agent token"}), 401

        g.machine_id = machine_id
        return f(*args, **kwargs)

    return decorated


def rate_limit_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or "unknown"
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=config.LOGIN_RATE_WINDOW)

        with _rate_lock:
            _login_attempts[ip] = [
                t for t in _login_attempts[ip] if t > cutoff
            ]
            if len(_login_attempts[ip]) >= config.LOGIN_RATE_LIMIT:
                logger.warning(f"Rate limit exceeded for IP: {ip}")
                return (
                    jsonify({
                        "error": "Too many login attempts. Try again later.",
                    }),
                    429,
                )
            _login_attempts[ip].append(now)

        return f(*args, **kwargs)

    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def validate_status_param(status: str) -> bool:
    return status in _VALID_STATUSES


# ─────────────────────────────────────────────────────────────────────────────
# Error handlers + security headers
# ─────────────────────────────────────────────────────────────────────────────

def handle_errors(app: Flask) -> None:
    """Register error handlers and a security-header after_request hook."""

    @app.after_request
    def add_security_headers(response):
        # Prevent clickjacking
        response.headers.setdefault("X-Frame-Options", "DENY")
        # Prevent MIME sniffing
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Basic XSS protection (legacy browsers)
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        # Remove server fingerprint
        response.headers.pop("Server", None)
        return response

    @app.errorhandler(400)
    def bad_request(exc):
        return jsonify({"error": "Bad request", "detail": str(exc)}), 400

    @app.errorhandler(404)
    def not_found(exc):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(exc):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(429)
    def too_many_requests(exc):
        return jsonify({"error": "Too many requests"}), 429

    @app.errorhandler(500)
    def internal_error(exc):
        logger.error(f"Internal server error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(Exception)
    def handle_exception(exc):
        # Don't swallow HTTP exceptions (werkzeug.exceptions.HTTPException)
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return exc

        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

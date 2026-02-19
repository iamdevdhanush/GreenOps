"""
GreenOps Authentication Routes
"""
import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request

from server.auth import AuthService
from server.config import config
from server.middleware import rate_limit_login, require_jwt

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.route("/login", methods=["POST"])
@rate_limit_login
def login():
    """
    POST /api/auth/login
    Body: {"username": "...", "password": "..."}
    Returns: {"token": "...", "expires_at": "...", "role": "...", "username": "..."}
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        username = data.get("username", "").strip()
        password = data.get("password", "")

        if not username or not password:
            return jsonify({"error": "Username and password required"}), 400

        if len(username) > 255 or len(password) > 1024:
            return jsonify({"error": "Invalid credentials"}), 401

        user = AuthService.authenticate_user(username, password)
        if not user:
            return jsonify({"error": "Invalid credentials"}), 401

        token = AuthService.generate_jwt(user["id"], user["username"], user["role"])
        expires_at = datetime.now(timezone.utc) + timedelta(hours=config.JWT_EXPIRATION_HOURS)

        return jsonify(
            {
                "token": token,
                "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "role": user["role"],
                "username": user["username"],
            }
        ), 200

    except Exception as exc:
        logger.error(f"Login error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@auth_bp.route("/verify", methods=["GET"])
@require_jwt
def verify():
    """
    GET /api/auth/verify
    Headers: Authorization: Bearer <jwt>
    Returns: {"valid": true, "username": "...", "role": "..."}
    """
    return jsonify(
        {
            "valid": True,
            "username": g.username,
            "role": g.role,
            "user_id": g.user_id,
        }
    ), 200

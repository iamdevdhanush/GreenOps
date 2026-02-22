"""
GreenOps Authentication Routes

POST /api/auth/login          — username+password → JWT
GET  /api/auth/verify         — validate JWT
POST /api/auth/change-password— change password (requires current password)

Safe fallback for must_change_password: if the column doesn't exist yet
(migration 003 hasn't run), we return False and let the user in rather
than crashing with a 500 UndefinedColumn error.
"""
import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request

from server.auth import AuthService
from server.config import config
from server.database import db
from server.middleware import rate_limit_login, require_jwt

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _get_must_change_password(user_id: int) -> bool:
    """
    Return must_change_password flag for the given user.
    Returns False (safe default) if the column doesn't exist yet.
    This prevents 500 errors on partially-migrated databases.
    """
    try:
        row = db.execute_one(
            "SELECT must_change_password FROM users WHERE id = %s",
            (user_id,),
        )
        return bool(row["must_change_password"]) if row else False
    except Exception as exc:
        # Column doesn't exist (UndefinedColumn) or other transient error.
        # Log at DEBUG level — this is expected on first boot before migration.
        logger.debug(
            f"could not read must_change_password for user {user_id}: {exc}"
        )
        return False


@auth_bp.route("/login", methods=["POST"])
@rate_limit_login
def login():
    """POST /api/auth/login — {username, password} → {token, ...}"""
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")

        if not username or not password:
            return jsonify({"error": "Username and password are required"}), 400

        # Prevent oversized payloads hitting the DB
        if len(username) > 255 or len(password) > 1024:
            return jsonify({"error": "Invalid credentials"}), 401

        user = AuthService.authenticate_user(username, password)
        if not user:
            return jsonify({"error": "Invalid credentials"}), 401

        must_change = _get_must_change_password(user["id"])
        token = AuthService.generate_jwt(user["id"], user["username"], user["role"])
        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=config.JWT_EXPIRATION_HOURS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        return jsonify({
            "token":                token,
            "expires_at":           expires_at,
            "role":                 user["role"],
            "username":             user["username"],
            "must_change_password": must_change,
        }), 200

    except Exception as exc:
        logger.error(f"Login error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@auth_bp.route("/change-password", methods=["POST"])
@require_jwt
def change_password():
    """POST /api/auth/change-password — {current_password, new_password}"""
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        current_pw = str(data.get("current_password") or "")
        new_pw     = str(data.get("new_password")     or "")

        if not current_pw or not new_pw:
            return jsonify(
                {"error": "current_password and new_password are required"}
            ), 400

        if len(new_pw) < 8:
            return jsonify(
                {"error": "New password must be at least 8 characters"}
            ), 422

        if len(new_pw) > 1024:
            return jsonify({"error": "New password is too long"}), 422

        # Re-authenticate to verify the current password
        user = AuthService.authenticate_user(g.username, current_pw)
        if not user:
            return jsonify({"error": "Current password is incorrect"}), 401

        new_hash = AuthService.hash_password(new_pw)
        db.execute_query(
            """
            UPDATE users
            SET    password_hash        = %s,
                   must_change_password = FALSE
            WHERE  id = %s
            """,
            (new_hash, g.user_id),
        )

        logger.info(f"Password changed for user id={g.user_id}")
        return jsonify({"message": "Password changed successfully"}), 200

    except Exception as exc:
        logger.error(f"Change-password error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@auth_bp.route("/verify", methods=["GET"])
@require_jwt
def verify():
    """GET /api/auth/verify — returns 200 if JWT is valid."""
    return jsonify({
        "valid":    True,
        "username": g.username,
        "role":     g.role,
        "user_id":  g.user_id,
    }), 200

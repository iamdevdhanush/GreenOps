"""
GreenOps Agent Routes
"""
import logging
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from server.middleware import require_agent_token
from server.services.machine import MachineService

logger = logging.getLogger(__name__)

agents_bp = Blueprint("agents", __name__, url_prefix="/api/agents")


@agents_bp.route("/health", methods=["GET"])
def health():
    """
    GET /api/agents/health  (no auth required)
    Returns: {"status": "healthy", "database": "connected", "timestamp": "..."}
    """
    try:
        from server.database import db
        db.execute_one("SELECT 1")
        return jsonify(
            {
                "status": "healthy",
                "database": "connected",
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ), 200
    except Exception as exc:
        logger.error(f"Health check failed: {exc}")
        return jsonify(
            {
                "status": "unhealthy",
                "database": "disconnected",
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ), 503


@agents_bp.route("/register", methods=["POST"])
def register():
    """
    POST /api/agents/register  (idempotent)
    Body: {"mac_address": "...", "hostname": "...", "os_type": "...", "os_version": "..."}
    Returns: {"token": "...", "machine_id": 42, "message": "..."}
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        required = ["mac_address", "hostname", "os_type"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

        mac_address = str(data["mac_address"]).strip()[:17]
        hostname = str(data["hostname"]).strip()[:255]
        os_type = str(data["os_type"]).strip()[:50]
        os_version = str(data.get("os_version", "")).strip()[:100] or None

        result = MachineService.register_machine(
            mac_address=mac_address,
            hostname=hostname,
            os_type=os_type,
            os_version=os_version,
        )

        logger.info(f"Agent registered: mac={mac_address[:8]}*** msg={result['message']}")
        return jsonify(result), 200

    except Exception as exc:
        logger.error(f"Agent registration error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@agents_bp.route("/heartbeat", methods=["POST"])
@require_agent_token
def heartbeat():
    """
    POST /api/agents/heartbeat
    Headers: Authorization: Bearer <agent_token>
    Body: {"idle_seconds": 600, "cpu_usage": 15.5, "memory_usage": 42.3, "timestamp": "..."}
    Returns: {"status": "ok", "machine_status": "idle", "energy_wasted_kwh": 12.456}
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        if "idle_seconds" not in data:
            return jsonify({"error": "idle_seconds required"}), 400

        try:
            idle_seconds = int(data["idle_seconds"])
            if idle_seconds < 0:
                return jsonify({"error": "idle_seconds must be non-negative"}), 422
        except (TypeError, ValueError):
            return jsonify({"error": "idle_seconds must be an integer"}), 422

        cpu_usage = None
        if data.get("cpu_usage") is not None:
            try:
                cpu_usage = float(data["cpu_usage"])
            except (TypeError, ValueError):
                pass

        memory_usage = None
        if data.get("memory_usage") is not None:
            try:
                memory_usage = float(data["memory_usage"])
            except (TypeError, ValueError):
                pass

        timestamp = None
        if data.get("timestamp"):
            try:
                raw = str(data["timestamp"]).replace("Z", "+00:00")
                timestamp = datetime.fromisoformat(raw)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
            except ValueError:
                return jsonify({"error": "Invalid timestamp format. Use ISO 8601."}), 422

        result = MachineService.process_heartbeat(
            machine_id=g.machine_id,
            idle_seconds=idle_seconds,
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            timestamp=timestamp,
        )

        return jsonify(result), 200

    except ValueError as exc:
        return jsonify({"error": f"Invalid data: {exc}"}), 422
    except Exception as exc:
        logger.error(f"Heartbeat error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

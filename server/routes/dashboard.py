"""
GreenOps Dashboard Routes
"""
import logging

from flask import Blueprint, jsonify, request

from server.database import db
from server.middleware import require_jwt, validate_status_param
from server.services.machine import MachineService

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api")


@dashboard_bp.route("/machines", methods=["GET"])
@require_jwt
def list_machines():
    """
    GET /api/machines?status=idle&limit=100&offset=0
    Headers: Authorization: Bearer <jwt>
    Returns: {"machines": [...], "total": 150}
    """
    try:
        status = request.args.get("status", "").strip() or None
        if status and not validate_status_param(status):
            return jsonify({"error": f"Invalid status. Must be one of: online, idle, offline"}), 422

        try:
            limit = min(int(request.args.get("limit", 100)), 1000)
            offset = max(int(request.args.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return jsonify({"error": "limit and offset must be integers"}), 422

        machines = MachineService.list_machines(
            status_filter=status, limit=limit, offset=offset
        )

        if status:
            total_result = db.execute_one(
                "SELECT COUNT(*) AS total FROM machines WHERE status = %s",
                (status,),
            )
        else:
            total_result = db.execute_one("SELECT COUNT(*) AS total FROM machines")

        total = total_result["total"] if total_result else 0

        formatted = []
        for m in machines:
            uptime_seconds = (m.get("total_idle_seconds") or 0) + (
                m.get("total_active_seconds") or 0
            )
            uptime_hours = round(uptime_seconds / 3600.0, 1)

            last_seen = None
            if m.get("last_seen"):
                last_seen = m["last_seen"].strftime("%Y-%m-%dT%H:%M:%SZ")

            formatted.append(
                {
                    "id": m["id"],
                    "mac_address": m["mac_address"],
                    "hostname": m["hostname"],
                    "os_type": m["os_type"],
                    "status": m["status"],
                    "last_seen": last_seen,
                    "energy_wasted_kwh": float(m["energy_wasted_kwh"] or 0),
                    "uptime_hours": uptime_hours,
                    "total_idle_seconds": m.get("total_idle_seconds") or 0,
                }
            )

        return jsonify({"machines": formatted, "total": total}), 200

    except Exception as exc:
        logger.error(f"List machines error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@dashboard_bp.route("/machines/<int:machine_id>", methods=["GET"])
@require_jwt
def get_machine(machine_id: int):
    """
    GET /api/machines/{id}
    Headers: Authorization: Bearer <jwt>
    """
    try:
        machine = MachineService.get_machine(machine_id)
        if not machine:
            return jsonify({"error": "Machine not found"}), 404

        for field in ["first_seen", "last_seen", "created_at", "updated_at"]:
            if machine.get(field):
                machine[field] = machine[field].strftime("%Y-%m-%dT%H:%M:%SZ")

        if machine.get("energy_wasted_kwh") is not None:
            machine["energy_wasted_kwh"] = float(machine["energy_wasted_kwh"])

        return jsonify(machine), 200

    except Exception as exc:
        logger.error(f"Get machine error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@dashboard_bp.route("/machines/<int:machine_id>/heartbeats", methods=["GET"])
@require_jwt
def get_machine_heartbeats(machine_id: int):
    """
    GET /api/machines/{id}/heartbeats?limit=100
    Headers: Authorization: Bearer <jwt>
    """
    try:
        try:
            limit = min(int(request.args.get("limit", 100)), 1000)
        except (TypeError, ValueError):
            limit = 100

        machine = MachineService.get_machine(machine_id)
        if not machine:
            return jsonify({"error": "Machine not found"}), 404

        heartbeats = db.execute_query(
            """
            SELECT id, timestamp, idle_seconds, cpu_usage, memory_usage, is_idle
            FROM heartbeats
            WHERE machine_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (machine_id, limit),
            fetch=True,
        )

        formatted = [
            {
                "id": hb["id"],
                "timestamp": hb["timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "idle_seconds": hb["idle_seconds"],
                "cpu_usage": float(hb["cpu_usage"]) if hb["cpu_usage"] is not None else None,
                "memory_usage": float(hb["memory_usage"]) if hb["memory_usage"] is not None else None,
                "is_idle": hb["is_idle"],
            }
            for hb in heartbeats
        ]

        return jsonify({"heartbeats": formatted, "machine_id": machine_id}), 200

    except Exception as exc:
        logger.error(f"Get heartbeats error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@dashboard_bp.route("/dashboard/stats", methods=["GET"])
@require_jwt
def get_dashboard_stats():
    """
    GET /api/dashboard/stats
    Headers: Authorization: Bearer <jwt>
    """
    try:
        stats = MachineService.get_dashboard_stats()
        return jsonify(stats), 200
    except Exception as exc:
        logger.error(f"Dashboard stats error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@dashboard_bp.route("/machines/<int:machine_id>", methods=["DELETE"])
@require_jwt
def delete_machine(machine_id: int):
    """
    DELETE /api/machines/{id}
    Headers: Authorization: Bearer <jwt>
    """
    try:
        machine = MachineService.get_machine(machine_id)
        if not machine:
            return jsonify({"error": "Machine not found"}), 404

        db.execute_query("DELETE FROM machines WHERE id = %s", (machine_id,))
        logger.info(f"Machine deleted: id={machine_id} hostname={machine['hostname']}")

        return jsonify({"message": "Machine deleted successfully", "machine_id": machine_id}), 200

    except Exception as exc:
        logger.error(f"Delete machine error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

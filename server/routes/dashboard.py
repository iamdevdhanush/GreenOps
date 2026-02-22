"""
GreenOps Dashboard Routes

GET    /api/machines               — paginated machine list
GET    /api/machines/{id}          — single machine detail
GET    /api/machines/{id}/heartbeats — recent heartbeat history
DELETE /api/machines/{id}          — remove machine record
POST   /api/machines/{id}/sleep    — queue sleep command
POST   /api/machines/{id}/shutdown — queue shutdown command
GET    /api/dashboard/stats        — aggregate summary stats
"""
import logging

from flask import Blueprint, g, jsonify, request

from server.database import db
from server.middleware import require_jwt, validate_status_param
from server.services.machine import MachineService

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api")


# ─────────────────────────────────────────────────────────────────────────────
# Machine list + detail
# ─────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/machines", methods=["GET"])
@require_jwt
def list_machines():
    try:
        status = (request.args.get("status") or "").strip() or None
        if status and not validate_status_param(status):
            return jsonify(
                {"error": "Invalid status. Must be: online, idle, offline"}
            ), 422

        try:
            limit  = min(int(request.args.get("limit",  100)), 1000)
            offset = max(int(request.args.get("offset", 0)),   0)
        except (TypeError, ValueError):
            return jsonify({"error": "limit and offset must be integers"}), 422

        machines = MachineService.list_machines(
            status_filter=status, limit=limit, offset=offset
        )

        # Total count (for pagination)
        if status:
            total_row = db.execute_one(
                "SELECT COUNT(*) AS total FROM machines WHERE status = %s",
                (status,),
            )
        else:
            total_row = db.execute_one("SELECT COUNT(*) AS total FROM machines")

        total = int(total_row["total"]) if total_row else 0

        formatted = []
        for m in machines:
            uptime_seconds = int(m.get("uptime_seconds") or 0)
            last_seen = (
                m["last_seen"].strftime("%Y-%m-%dT%H:%M:%SZ")
                if m.get("last_seen") else None
            )
            formatted.append({
                "id":                m["id"],
                "mac_address":       m["mac_address"],
                "hostname":          m["hostname"],
                "os_type":           m["os_type"],
                "status":            m["status"],
                "last_seen":         last_seen,
                "energy_wasted_kwh": float(m.get("energy_wasted_kwh") or 0),
                "uptime_seconds":    uptime_seconds,
                "uptime_hours":      round(uptime_seconds / 3600.0, 1),
                "total_idle_seconds": int(m.get("total_idle_seconds") or 0),
            })

        return jsonify({"machines": formatted, "total": total}), 200

    except Exception as exc:
        logger.error(f"list_machines error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@dashboard_bp.route("/machines/<int:machine_id>", methods=["GET"])
@require_jwt
def get_machine(machine_id: int):
    try:
        machine = MachineService.get_machine(machine_id)
        if not machine:
            return jsonify({"error": "Machine not found"}), 404

        for field in ("first_seen", "last_seen", "created_at", "updated_at"):
            if machine.get(field):
                machine[field] = machine[field].strftime("%Y-%m-%dT%H:%M:%SZ")

        if machine.get("energy_wasted_kwh") is not None:
            machine["energy_wasted_kwh"] = float(machine["energy_wasted_kwh"])

        return jsonify(machine), 200

    except Exception as exc:
        logger.error(f"get_machine error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@dashboard_bp.route("/machines/<int:machine_id>/heartbeats", methods=["GET"])
@require_jwt
def get_machine_heartbeats(machine_id: int):
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
            FROM   heartbeats
            WHERE  machine_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (machine_id, limit),
            fetch=True,
        )

        formatted = [
            {
                "id":           hb["id"],
                "timestamp":    hb["timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "idle_seconds": hb["idle_seconds"],
                "cpu_usage":    float(hb["cpu_usage"])    if hb["cpu_usage"]    is not None else None,
                "memory_usage": float(hb["memory_usage"]) if hb["memory_usage"] is not None else None,
                "is_idle":      hb["is_idle"],
            }
            for hb in (heartbeats or [])
        ]

        return jsonify({"heartbeats": formatted, "machine_id": machine_id}), 200

    except Exception as exc:
        logger.error(f"get_machine_heartbeats error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@dashboard_bp.route("/machines/<int:machine_id>", methods=["DELETE"])
@require_jwt
def delete_machine(machine_id: int):
    try:
        machine = MachineService.get_machine(machine_id)
        if not machine:
            return jsonify({"error": "Machine not found"}), 404

        db.execute_query("DELETE FROM machines WHERE id = %s", (machine_id,))
        logger.info(f"Machine deleted: id={machine_id} hostname={machine['hostname']}")
        return jsonify({"message": "Machine deleted"}), 200

    except Exception as exc:
        logger.error(f"delete_machine error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard stats
# ─────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/dashboard/stats", methods=["GET"])
@require_jwt
def get_dashboard_stats():
    try:
        stats = MachineService.get_dashboard_stats()
        return jsonify(stats), 200
    except Exception as exc:
        logger.error(f"get_dashboard_stats error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Remote commands: sleep / shutdown
# ─────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/machines/<int:machine_id>/sleep", methods=["POST"])
@require_jwt
def sleep_machine(machine_id: int):
    return _queue_command(machine_id, "sleep")


@dashboard_bp.route("/machines/<int:machine_id>/shutdown", methods=["POST"])
@require_jwt
def shutdown_machine(machine_id: int):
    return _queue_command(machine_id, "shutdown")


def _queue_command(machine_id: int, command: str):
    """
    Insert a pending command.  Agent picks it up on next heartbeat poll.
    Validates:
    - machine exists
    - machine is not offline
    - g.user_id is set (jwt decorator guarantees this)
    """
    try:
        machine = MachineService.get_machine(machine_id)
        if not machine:
            return jsonify({"error": "Machine not found"}), 404

        if machine["status"] == "offline":
            return jsonify(
                {"error": "Cannot send command to an offline machine"}
            ), 409

        # Expire any existing pending commands first (avoid command queue pile-up)
        db.execute_query(
            """
            UPDATE machine_commands
            SET    status = 'expired'
            WHERE  machine_id = %s
              AND  status     = 'pending'
            """,
            (machine_id,),
        )

        row = db.execute_one(
            """
            INSERT INTO machine_commands (machine_id, command, created_by)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (machine_id, command, g.user_id),
        )

        if not row:
            raise RuntimeError("INSERT RETURNING returned no row.")

        logger.info(
            f"Command '{command}' queued for machine {machine_id} "
            f"by user {g.user_id} (cmd_id={row['id']})"
        )

        return jsonify({
            "message":    f"'{command}' command queued. Agent will execute on next poll.",
            "command_id": row["id"],
            "machine_id": machine_id,
        }), 202

    except Exception as exc:
        logger.error(f"_queue_command error: {exc}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

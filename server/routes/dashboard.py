"""
GreenOps Dashboard Routes
"""
from flask import Blueprint, request, jsonify
import logging

from server.services.machine import MachineService
from server.middleware import require_jwt
from server.database import db

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api')

@dashboard_bp.route('/machines', methods=['GET'])
@require_jwt
def list_machines():
    """
    List all machines with optional filtering
    
    GET /api/machines?status=idle&limit=100&offset=0
    Headers: Authorization: Bearer <jwt>
    Returns: {
        "machines": [...],
        "total": 150
    }
    """
    try:
        status = request.args.get('status')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        
        # Validate limit
        if limit > 1000:
            limit = 1000
        
        machines = MachineService.list_machines(
            status_filter=status,
            limit=limit,
            offset=offset
        )
        
        # Get total count
        count_query = "SELECT COUNT(*) as total FROM machines"
        if status:
            count_query += f" WHERE status = '{status}'"
        
        total_result = db.execute_one(count_query)
        total = total_result['total'] if total_result else 0
        
        # Format response
        formatted_machines = []
        for m in machines:
            # Calculate uptime
            if m['last_seen']:
                uptime_seconds = (m['total_idle_seconds'] or 0) + (m['total_active_seconds'] or 0)
                uptime_hours = uptime_seconds / 3600.0
            else:
                uptime_hours = 0
            
            formatted_machines.append({
                'id': m['id'],
                'mac_address': m['mac_address'],
                'hostname': m['hostname'],
                'os_type': m['os_type'],
                'status': m['status'],
                'last_seen': m['last_seen'].isoformat() + 'Z' if m['last_seen'] else None,
                'energy_wasted_kwh': float(m['energy_wasted_kwh']) if m['energy_wasted_kwh'] else 0.0,
                'uptime_hours': round(uptime_hours, 1),
                'total_idle_seconds': m['total_idle_seconds'] or 0
            })
        
        return jsonify({
            'machines': formatted_machines,
            'total': total
        }), 200
        
    except Exception as e:
        logger.error(f"List machines error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@dashboard_bp.route('/machines/<int:machine_id>', methods=['GET'])
@require_jwt
def get_machine(machine_id):
    """
    Get machine details
    
    GET /api/machines/{id}
    Headers: Authorization: Bearer <jwt>
    Returns: machine details
    """
    try:
        machine = MachineService.get_machine(machine_id)
        
        if not machine:
            return jsonify({'error': 'Machine not found'}), 404
        
        # Format timestamps
        for field in ['first_seen', 'last_seen', 'created_at', 'updated_at']:
            if machine.get(field):
                machine[field] = machine[field].isoformat() + 'Z'
        
        # Convert Decimal to float
        if machine.get('energy_wasted_kwh'):
            machine['energy_wasted_kwh'] = float(machine['energy_wasted_kwh'])
        
        return jsonify(machine), 200
        
    except Exception as e:
        logger.error(f"Get machine error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@dashboard_bp.route('/machines/<int:machine_id>/heartbeats', methods=['GET'])
@require_jwt
def get_machine_heartbeats(machine_id):
    """
    Get recent heartbeats for a machine
    
    GET /api/machines/{id}/heartbeats?limit=100
    Headers: Authorization: Bearer <jwt>
    Returns: list of heartbeats
    """
    try:
        limit = int(request.args.get('limit', 100))
        
        query = """
            SELECT id, timestamp, idle_seconds, cpu_usage, memory_usage, is_idle
            FROM heartbeats
            WHERE machine_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        heartbeats = db.execute_query(query, (machine_id, limit), fetch=True)
        
        # Format response
        formatted = []
        for hb in heartbeats:
            formatted.append({
                'id': hb['id'],
                'timestamp': hb['timestamp'].isoformat() + 'Z',
                'idle_seconds': hb['idle_seconds'],
                'cpu_usage': float(hb['cpu_usage']) if hb['cpu_usage'] else None,
                'memory_usage': float(hb['memory_usage']) if hb['memory_usage'] else None,
                'is_idle': hb['is_idle']
            })
        
        return jsonify({
            'heartbeats': formatted,
            'machine_id': machine_id
        }), 200
        
    except Exception as e:
        logger.error(f"Get heartbeats error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@dashboard_bp.route('/dashboard/stats', methods=['GET'])
@require_jwt
def get_dashboard_stats():
    """
    Get aggregate statistics
    
    GET /api/dashboard/stats
    Headers: Authorization: Bearer <jwt>
    Returns: aggregate stats
    """
    try:
        stats = MachineService.get_dashboard_stats()
        return jsonify(stats), 200
        
    except Exception as e:
        logger.error(f"Dashboard stats error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@dashboard_bp.route('/machines/<int:machine_id>', methods=['DELETE'])
@require_jwt
def delete_machine(machine_id):
    """
    Delete machine (admin only in production)
    
    DELETE /api/machines/{id}
    Headers: Authorization: Bearer <jwt>
    Returns: success message
    """
    try:
        # Check if machine exists
        machine = MachineService.get_machine(machine_id)
        
        if not machine:
            return jsonify({'error': 'Machine not found'}), 404
        
        # Delete machine (CASCADE will delete heartbeats and tokens)
        query = "DELETE FROM machines WHERE id = %s"
        db.execute_query(query, (machine_id,))
        
        logger.info(f"Machine deleted: {machine_id} ({machine['hostname']})")
        
        return jsonify({
            'message': 'Machine deleted successfully',
            'machine_id': machine_id
        }), 200
        
    except Exception as e:
        logger.error(f"Delete machine error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

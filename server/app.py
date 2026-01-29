"""
GreenOps Server v2.0
Enterprise Carbon Governance Platform
"""

from flask import Flask, request, render_template, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import os
import csv
import json
from io import StringIO
import logging
from logging.handlers import RotatingFileHandler

# ----------------------
# CONFIGURATION
# ----------------------
class Config:
    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///greenops.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Security
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
    
    # Carbon Settings
    CARBON_BUDGET_MONTHLY = int(os.getenv('CARBON_BUDGET_MONTHLY', 5000))
    CO2_FACTOR = float(os.getenv('CO2_FACTOR', 0.82))
    COST_PER_KWH = float(os.getenv('COST_PER_KWH', 8))
    
    # Power Settings
    DEFAULT_POWER_WATTS = 150
    MONITOR_POWER_WATTS = 30
    
    # Features
    DEMO_MODE = os.getenv('DEMO_MODE', 'true').lower() == 'true'
    ENABLE_ML_PREDICTIONS = os.getenv('ENABLE_ML_PREDICTIONS', 'false').lower() == 'true'
    
    # Rate Limiting
    RATELIMIT_STORAGE_URL = "memory://"

# ----------------------
# APP INITIALIZATION
# ----------------------
app = Flask(__name__)
app.config.from_object(Config)

# Extensions
db = SQLAlchemy(app)
jwt = JWTManager(app)
CORS(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Logging
if not os.path.exists('logs'):
    os.makedirs('logs')

file_handler = RotatingFileHandler('logs/greenops.log', maxBytes=10240000, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('GreenOps startup')

# ----------------------
# DATABASE MODELS
# ----------------------
class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='viewer')  # admin, manager, viewer
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'department_id': self.department_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Department(db.Model):
    __tablename__ = 'departments'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    carbon_budget = db.Column(db.Float, default=1000.0)
    cost_center = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    users = db.relationship('User', backref='department', lazy=True)
    systems = db.relationship('System', backref='department', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'carbon_budget': self.carbon_budget,
            'cost_center': self.cost_center,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class System(db.Model):
    __tablename__ = 'systems'
    
    id = db.Column(db.Integer, primary_key=True)
    pc_id = db.Column(db.String(100), unique=True, nullable=False)
    hostname = db.Column(db.String(255))
    os = db.Column(db.String(50))
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    power_watts = db.Column(db.Integer, default=150)
    status = db.Column(db.String(20), default='active')  # active, idle, sleeping, offline
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    agent_version = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'pc_id': self.pc_id,
            'hostname': self.hostname,
            'os': self.os,
            'department_id': self.department_id,
            'power_watts': self.power_watts,
            'status': self.status,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'registered_at': self.registered_at.isoformat() if self.registered_at else None
        }

class AgentLog(db.Model):
    __tablename__ = 'agent_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    system_id = db.Column(db.Integer, db.ForeignKey('systems.id'))
    pc_id = db.Column(db.String(100), nullable=False)
    idle_minutes = db.Column(db.Float, nullable=False)
    action = db.Column(db.String(50), nullable=False)
    reason = db.Column(db.String(255))
    energy_kwh = db.Column(db.Float)
    co2_kg = db.Column(db.Float)
    cost_saved = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    system = db.relationship('System', backref='logs')
    
    def to_dict(self):
        return {
            'id': self.id,
            'pc_id': self.pc_id,
            'idle_minutes': self.idle_minutes,
            'action': self.action,
            'reason': self.reason,
            'energy_kwh': self.energy_kwh,
            'co2_kg': self.co2_kg,
            'cost_saved': self.cost_saved,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }

class Policy(db.Model):
    __tablename__ = 'policies'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    idle_threshold = db.Column(db.Integer, default=15)  # minutes
    sleep_threshold = db.Column(db.Integer, default=30)  # minutes
    action_type = db.Column(db.String(20), default='sleep')  # sleep, hibernate, shutdown
    warning_enabled = db.Column(db.Boolean, default=True)
    warning_duration = db.Column(db.Integer, default=300)  # seconds
    schedule = db.Column(db.String(100))  # e.g., "Mon-Fri 9:00-18:00"
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'idle_threshold': self.idle_threshold,
            'sleep_threshold': self.sleep_threshold,
            'action_type': self.action_type,
            'warning_enabled': self.warning_enabled,
            'warning_duration': self.warning_duration,
            'schedule': self.schedule,
            'is_active': self.is_active
        }

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)
    resource = db.Column(db.String(100))
    resource_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    user = db.relationship('User', backref='audit_logs')

# ----------------------
# DECORATORS
# ----------------------
def admin_required(f):
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user or user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

def log_audit(action, resource=None, resource_id=None, details=None):
    """Log audit trail"""
    try:
        audit = AuditLog(
            user_id=get_jwt_identity() if jwt_required else None,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details,
            ip_address=request.remote_addr
        )
        db.session.add(audit)
        db.session.commit()
    except Exception as e:
        app.logger.error(f"Audit log error: {e}")

# ----------------------
# HELPER FUNCTIONS
# ----------------------
def calculate_metrics(idle_minutes, power_watts=None):
    """Calculate energy, CO2, and cost metrics"""
    if power_watts is None:
        power_watts = Config.DEFAULT_POWER_WATTS
    
    energy_kwh = (power_watts * (idle_minutes / 60)) / 1000
    co2_kg = energy_kwh * Config.CO2_FACTOR
    cost_saved = energy_kwh * Config.COST_PER_KWH
    
    return {
        'energy_kwh': round(energy_kwh, 3),
        'co2_kg': round(co2_kg, 3),
        'cost_saved': round(cost_saved, 2)
    }

def get_or_create_system(pc_id, os_name=None):
    """Get existing system or create new one"""
    system = System.query.filter_by(pc_id=pc_id).first()
    if not system:
        system = System(
            pc_id=pc_id,
            hostname=pc_id,
            os=os_name,
            status='active'
        )
        db.session.add(system)
        db.session.commit()
        app.logger.info(f"New system registered: {pc_id}")
    else:
        system.last_seen = datetime.utcnow()
        db.session.commit()
    return system

# ----------------------
# AUTHENTICATION ROUTES
# ----------------------
@app.route('/api/v1/auth/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    """User login endpoint"""
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Missing credentials'}), 400
    
    user = User.query.filter_by(username=data['username']).first()
    
    if not user or not user.check_password(data['password']) or not user.is_active:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    user.last_login = datetime.utcnow()
    db.session.commit()
    
    access_token = create_access_token(identity=user.id)
    
    log_audit('login', 'user', user.id)
    
    return jsonify({
        'access_token': access_token,
        'user': user.to_dict()
    }), 200

@app.route('/api/v1/auth/register', methods=['POST'])
@admin_required
def register():
    """Register new user (admin only)"""
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('password') or not data.get('email'):
        return jsonify({'error': 'Missing required fields'}), 400
    
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 400
    
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already exists'}), 400
    
    user = User(
        username=data['username'],
        email=data['email'],
        role=data.get('role', 'viewer'),
        department_id=data.get('department_id')
    )
    user.set_password(data['password'])
    
    db.session.add(user)
    db.session.commit()
    
    log_audit('register_user', 'user', user.id)
    
    return jsonify({'message': 'User created', 'user': user.to_dict()}), 201

# ----------------------
# DASHBOARD ROUTE
# ----------------------
@app.route('/')
def dashboard():
    """Main dashboard view"""
    # Get recent logs
    logs_query = AgentLog.query.order_by(AgentLog.timestamp.desc()).limit(20).all()
    
    # Demo data if no logs
    if not logs_query:
        logs_data = [
            {"pc_id": "PC-01", "idle_minutes": 25, "action": "SLEEP"},
            {"pc_id": "PC-02", "idle_minutes": 10, "action": "NONE"},
            {"pc_id": "PC-03", "idle_minutes": 45, "action": "SLEEP"},
        ]
    else:
        logs_data = [log.to_dict() for log in logs_query]
    
    # Calculate totals
    total_idle = sum(log.get('idle_minutes', 0) for log in logs_data)
    total_energy = sum(log.get('energy_kwh', 0) for log in logs_data)
    total_co2 = sum(log.get('co2_kg', 0) for log in logs_data)
    total_cost_saved = sum(log.get('cost_saved', 0) for log in logs_data)
    
    # If no calculated values, estimate
    if total_energy == 0 and total_idle > 0:
        metrics = calculate_metrics(total_idle)
        total_energy = metrics['energy_kwh']
        total_co2 = metrics['co2_kg']
        total_cost_saved = metrics['cost_saved']
    
    optimized = len([l for l in logs_data if l['action'] in ['SLEEP', 'HIBERNATE']])
    active = len([l for l in logs_data if l['action'] == 'NONE'])
    
    # System counts
    total_systems = System.query.filter_by(is_active=True).count()
    online_systems = System.query.filter(
        System.is_active == True,
        System.last_seen >= datetime.utcnow() - timedelta(minutes=5)
    ).count()
    
    remaining_budget = Config.CARBON_BUDGET_MONTHLY - total_co2
    budget_percentage = (total_co2 / Config.CARBON_BUDGET_MONTHLY) * 100 if Config.CARBON_BUDGET_MONTHLY > 0 else 0
    
    return render_template(
        'dashboard.html',
        energy=round(total_energy, 2),
        co2=round(total_co2, 2),
        remaining=round(remaining_budget, 2),
        used=round(total_co2, 2),
        budget_percentage=round(budget_percentage, 1),
        optimized=optimized,
        active=active,
        money_saved=round(total_cost_saved, 2),
        total_systems=total_systems,
        online_systems=online_systems,
        logs=logs_data[:10],
        demo_mode=Config.DEMO_MODE
    )

# ----------------------
# AGENT API
# ----------------------
@app.route('/api/v1/agent/report', methods=['POST'])
@limiter.limit("120 per minute")
def agent_report():
    """Receive agent reports"""
    data = request.get_json()
    
    if not data or not data.get('pc_id'):
        return jsonify({'error': 'Missing pc_id'}), 400
    
    pc_id = data['pc_id']
    idle_minutes = data.get('idle_minutes', 0)
    action = data.get('action', 'NONE')
    os_name = data.get('os')
    
    # Get or create system
    system = get_or_create_system(pc_id, os_name)
    
    # Update system status
    if idle_minutes > 30:
        system.status = 'idle'
    elif action in ['SLEEP', 'HIBERNATE']:
        system.status = 'sleeping'
    else:
        system.status = 'active'
    
    # Calculate metrics
    metrics = calculate_metrics(idle_minutes, system.power_watts)
    
    # Determine reason
    reason = None
    if action == 'SLEEP':
        reason = f'Idle exceeded {data.get("threshold", 15)} minute threshold'
    elif action == 'NONE':
        reason = 'Within allowed activity window'
    
    # Create log entry
    log_entry = AgentLog(
        system_id=system.id,
        pc_id=pc_id,
        idle_minutes=idle_minutes,
        action=action,
        reason=reason,
        energy_kwh=metrics['energy_kwh'],
        co2_kg=metrics['co2_kg'],
        cost_saved=metrics['cost_saved'] if action != 'NONE' else 0
    )
    
    db.session.add(log_entry)
    db.session.commit()
    
    app.logger.info(f"Report from {pc_id}: idle={idle_minutes}min, action={action}")
    
    return jsonify({
        'status': 'ok',
        'system_id': system.id,
        'metrics': metrics
    }), 200

@app.route('/api/v1/agent/policy', methods=['GET'])
def agent_policy():
    """Get active policy for agent"""
    active_policy = Policy.query.filter_by(is_active=True).first()
    
    if not active_policy:
        # Return default policy
        return jsonify({
            'idle_threshold': 15,
            'sleep_threshold': 30,
            'action_type': 'sleep',
            'warning_enabled': True,
            'warning_duration': 300
        }), 200
    
    return jsonify(active_policy.to_dict()), 200

# ----------------------
# SYSTEMS API
# ----------------------
@app.route('/api/v1/systems', methods=['GET'])
@jwt_required()
def get_systems():
    """Get all systems"""
    systems = System.query.filter_by(is_active=True).all()
    return jsonify([s.to_dict() for s in systems]), 200

@app.route('/api/v1/systems/<int:system_id>', methods=['GET'])
@jwt_required()
def get_system(system_id):
    """Get specific system"""
    system = System.query.get_or_404(system_id)
    
    # Get recent logs
    recent_logs = AgentLog.query.filter_by(system_id=system_id)\
        .order_by(AgentLog.timestamp.desc())\
        .limit(10).all()
    
    return jsonify({
        'system': system.to_dict(),
        'recent_logs': [log.to_dict() for log in recent_logs]
    }), 200

# ----------------------
# METRICS API
# ----------------------
@app.route('/api/v1/metrics/summary', methods=['GET'])
@jwt_required()
def metrics_summary():
    """Get summary metrics"""
    period = request.args.get('period', '7d')
    
    # Calculate time range
    if period == '24h':
        since = datetime.utcnow() - timedelta(days=1)
    elif period == '7d':
        since = datetime.utcnow() - timedelta(days=7)
    elif period == '30d':
        since = datetime.utcnow() - timedelta(days=30)
    else:
        since = datetime.utcnow() - timedelta(days=7)
    
    # Query logs
    logs = AgentLog.query.filter(AgentLog.timestamp >= since).all()
    
    total_energy = sum(log.energy_kwh or 0 for log in logs)
    total_co2 = sum(log.co2_kg or 0 for log in logs)
    total_cost_saved = sum(log.cost_saved or 0 for log in logs)
    total_actions = len([l for l in logs if l.action != 'NONE'])
    
    return jsonify({
        'period': period,
        'total_energy_kwh': round(total_energy, 2),
        'total_co2_kg': round(total_co2, 2),
        'total_cost_saved': round(total_cost_saved, 2),
        'total_actions': total_actions,
        'carbon_budget': Config.CARBON_BUDGET_MONTHLY,
        'budget_remaining': round(Config.CARBON_BUDGET_MONTHLY - total_co2, 2),
        'budget_used_percentage': round((total_co2 / Config.CARBON_BUDGET_MONTHLY) * 100, 1)
    }), 200

@app.route('/api/v1/metrics/trends', methods=['GET'])
@jwt_required()
def metrics_trends():
    """Get time-series metrics"""
    days = int(request.args.get('days', 7))
    since = datetime.utcnow() - timedelta(days=days)
    
    logs = AgentLog.query.filter(AgentLog.timestamp >= since).all()
    
    # Group by date
    daily_metrics = {}
    for log in logs:
        date_key = log.timestamp.strftime('%Y-%m-%d')
        if date_key not in daily_metrics:
            daily_metrics[date_key] = {
                'date': date_key,
                'energy_kwh': 0,
                'co2_kg': 0,
                'cost_saved': 0,
                'actions': 0
            }
        daily_metrics[date_key]['energy_kwh'] += log.energy_kwh or 0
        daily_metrics[date_key]['co2_kg'] += log.co2_kg or 0
        daily_metrics[date_key]['cost_saved'] += log.cost_saved or 0
        if log.action != 'NONE':
            daily_metrics[date_key]['actions'] += 1
    
    return jsonify({
        'trends': list(daily_metrics.values())
    }), 200

# ----------------------
# EXPORT ROUTES
# ----------------------
@app.route('/api/v1/export/csv', methods=['GET'])
@jwt_required()
def export_csv():
    """Export logs as CSV"""
    period = request.args.get('period', '30d')
    
    if period == '7d':
        since = datetime.utcnow() - timedelta(days=7)
    elif period == '30d':
        since = datetime.utcnow() - timedelta(days=30)
    elif period == 'all':
        since = datetime(2020, 1, 1)
    else:
        since = datetime.utcnow() - timedelta(days=30)
    
    logs = AgentLog.query.filter(AgentLog.timestamp >= since)\
        .order_by(AgentLog.timestamp.desc()).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'Timestamp', 'System ID', 'Idle Minutes', 'Action',
        'Energy (kWh)', 'CO2 (kg)', 'Cost Saved (₹)', 'Reason'
    ])
    
    # Data
    for log in logs:
        writer.writerow([
            log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            log.pc_id,
            log.idle_minutes,
            log.action,
            log.energy_kwh or 0,
            log.co2_kg or 0,
            log.cost_saved or 0,
            log.reason or ''
        ])
    
    output.seek(0)
    
    log_audit('export_csv', 'logs', None, f'Exported {len(logs)} records')
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=greenops_export_{datetime.now().strftime("%Y%m%d")}.csv'
        }
    )

# ----------------------
# POLICIES API
# ----------------------
@app.route('/api/v1/policies', methods=['GET'])
@jwt_required()
def get_policies():
    """Get all policies"""
    policies = Policy.query.all()
    return jsonify([p.to_dict() for p in policies]), 200

@app.route('/api/v1/policies', methods=['POST'])
@admin_required
def create_policy():
    """Create new policy"""
    data = request.get_json()
    
    policy = Policy(
        name=data['name'],
        description=data.get('description'),
        idle_threshold=data.get('idle_threshold', 15),
        sleep_threshold=data.get('sleep_threshold', 30),
        action_type=data.get('action_type', 'sleep'),
        warning_enabled=data.get('warning_enabled', True),
        warning_duration=data.get('warning_duration', 300),
        schedule=data.get('schedule')
    )
    
    db.session.add(policy)
    db.session.commit()
    
    log_audit('create_policy', 'policy', policy.id, data['name'])
    
    return jsonify(policy.to_dict()), 201

# ----------------------
# HEALTH CHECK
# ----------------------
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    try:
        # Check database
        db.session.execute('SELECT 1')
        db_status = 'ok'
    except Exception as e:
        db_status = f'error: {str(e)}'
    
    return jsonify({
        'status': 'ok',
        'version': '2.0.0',
        'database': db_status,
        'demo_mode': Config.DEMO_MODE
    }), 200

# ----------------------
# PROMETHEUS METRICS
# ----------------------
@app.route('/metrics', methods=['GET'])
def prometheus_metrics():
    """Prometheus metrics endpoint"""
    logs = AgentLog.query.filter(
        AgentLog.timestamp >= datetime.utcnow() - timedelta(hours=24)
    ).all()
    
    total_co2 = sum(log.co2_kg or 0 for log in logs)
    total_energy = sum(log.energy_kwh or 0 for log in logs)
    total_actions = len([l for l in logs if l.action != 'NONE'])
    
    systems_active = System.query.filter_by(status='active', is_active=True).count()
    systems_idle = System.query.filter_by(status='idle', is_active=True).count()
    systems_sleeping = System.query.filter_by(status='sleeping', is_active=True).count()
    
    metrics = f"""# HELP greenops_carbon_emissions_kg Total carbon emissions in kg
# TYPE greenops_carbon_emissions_kg gauge
greenops_carbon_emissions_kg {total_co2}

# HELP greenops_energy_kwh Total energy consumption in kWh
# TYPE greenops_energy_kwh gauge
greenops_energy_kwh {total_energy}

# HELP greenops_actions_total Total power management actions
# TYPE greenops_actions_total counter
greenops_actions_total {total_actions}

# HELP greenops_systems_active Number of active systems
# TYPE greenops_systems_active gauge
greenops_systems_active {systems_active}

# HELP greenops_systems_idle Number of idle systems
# TYPE greenops_systems_idle gauge
greenops_systems_idle {systems_idle}

# HELP greenops_systems_sleeping Number of sleeping systems
# TYPE greenops_systems_sleeping gauge
greenops_systems_sleeping {systems_sleeping}
"""
    
    return Response(metrics, mimetype='text/plain')

# ----------------------
# ERROR HANDLERS
# ----------------------
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    app.logger.error(f'Server Error: {error}')
    return jsonify({'error': 'Internal server error'}), 500

# ----------------------
# INITIALIZE DATABASE
# ----------------------
with app.app_context():
    db.create_all()
    
    # Create default admin user if not exists
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            email='admin@greenops.local',
            role='admin'
        )
        admin.set_password('changeme')
        db.session.add(admin)
        
        # Create default department
        default_dept = Department(
            name='Default',
            carbon_budget=5000,
            cost_center='DEFAULT'
        )
        db.session.add(default_dept)
        
        # Create default policy
        default_policy = Policy(
            name='Default Policy',
            description='Standard office hours policy',
            idle_threshold=15,
            sleep_threshold=30,
            action_type='sleep',
            warning_enabled=True,
            is_active=True
        )
        db.session.add(default_policy)
        
        db.session.commit()
        app.logger.info('Default admin user and policy created')

# ----------------------
# START SERVER
# ----------------------
if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=not Config.DEMO_MODE
    )

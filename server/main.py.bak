"""
GreenOps Server
Main application entry point
"""
import sys
import logging
from logging.handlers import RotatingFileHandler
import signal
from flask import Flask, jsonify
from flask_cors import CORS

from server.config import config
from server.database import db
from server.middleware import handle_errors
from server.routes.auth import auth_bp
from server.routes.agents import agents_bp
from server.routes.dashboard import dashboard_bp
from server.services.machine import MachineService

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            config.LOG_FILE,
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5
        ),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def create_app():
    """Application factory"""
    
    # Validate configuration
    try:
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    
    # Create Flask app
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False
    
    # Enable CORS
    CORS(app, origins=config.CORS_ORIGINS, supports_credentials=True)
    
    # Initialize database
    try:
        db.initialize()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        sys.exit(1)
    
    # Register error handlers
    handle_errors(app)
    
    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(dashboard_bp)
    
    # Root endpoint
    @app.route('/')
    def root():
        return jsonify({
            'service': 'GreenOps',
            'version': '1.0.0',
            'status': 'operational'
        })
    
    # Health check
    @app.route('/health')
    def health():
        return jsonify({
            'status': 'healthy',
            'database': 'connected'
        })
    
    logger.info("GreenOps server initialized")
    
    return app

def graceful_shutdown(signum, frame):
    """Handle graceful shutdown"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    db.close()
    sys.exit(0)

def main():
    """Main entry point"""
    
    # Register signal handlers
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    
    # Create app
    app = create_app()
    
    # Start background task for marking offline machines
    # In production, use celery or APScheduler
    # For now, we'll do it on-demand via heartbeat processing
    
    logger.info(f"Starting GreenOps server on {config.HOST}:{config.PORT}")
    
    # Run server
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        threaded=True
    )

if __name__ == '__main__':
    main()

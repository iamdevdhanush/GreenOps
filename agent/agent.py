"""
GreenOps Agent v2.0
Cross-platform system monitoring agent with advanced power management
"""

import time
import platform
import requests
import json
import logging
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Try to import optional dependencies
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("Warning: psutil not installed. Some features will be limited.")

# Platform-specific imports
OS = platform.system()

if OS == "Linux":
    from idle_linux import get_idle_minutes_linux
    from power_linux import sleep_linux, hibernate_linux
elif OS == "Windows":
    from idle_windows import get_idle_minutes_windows
    from power_windows import sleep_windows, hibernate_windows
elif OS == "Darwin":  # macOS
    from idle_macos import get_idle_minutes_macos
    from power_macos import sleep_macos

# ----------------------
# CONFIGURATION
# ----------------------
class Config:
    """Agent configuration"""
    # Server
    SERVER_URL = os.getenv('GREENOPS_SERVER', 'http://localhost:5000')
    API_KEY = os.getenv('GREENOPS_API_KEY', '')
    
    # Policies
    IDLE_THRESHOLD = 15  # minutes
    SLEEP_THRESHOLD = 30  # minutes
    WARNING_DURATION = 300  # seconds (5 minutes)
    
    # System
    CHECK_INTERVAL = 60  # seconds
    POWER_WATTS = 150
    MONITOR_WATTS = 30
    
    # Features
    DEMO_MODE = os.getenv('DEMO_MODE', 'true').lower() == 'true'
    ENABLE_WARNINGS = True
    DETECT_UNSAVED_WORK = True
    
    # Retry settings
    MAX_RETRIES = 3
    RETRY_DELAY = 5
    
    # Logging
    LOG_LEVEL = logging.INFO
    LOG_FILE = 'greenops_agent.log'
    
    @classmethod
    def load_from_file(cls, config_path='config.json'):
        """Load configuration from JSON file"""
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    
                cls.SERVER_URL = config.get('server_url', cls.SERVER_URL)
                cls.API_KEY = config.get('api_key', cls.API_KEY)
                
                policies = config.get('policies', {})
                cls.IDLE_THRESHOLD = policies.get('idle_threshold_minutes', cls.IDLE_THRESHOLD)
                cls.SLEEP_THRESHOLD = policies.get('sleep_after_minutes', cls.SLEEP_THRESHOLD)
                cls.WARNING_DURATION = policies.get('warning_duration_seconds', cls.WARNING_DURATION)
                cls.ENABLE_WARNINGS = policies.get('warn_before_action', cls.ENABLE_WARNINGS)
                
                system = config.get('system', {})
                cls.POWER_WATTS = system.get('power_watts', cls.POWER_WATTS)
                cls.MONITOR_WATTS = system.get('monitor_power_watts', cls.MONITOR_WATTS)
                
                cls.CHECK_INTERVAL = config.get('check_interval', cls.CHECK_INTERVAL)
                
                logging.info(f"Configuration loaded from {config_path}")
            except Exception as e:
                logging.error(f"Failed to load config: {e}")

# ----------------------
# LOGGING SETUP
# ----------------------
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('GreenOpsAgent')

# ----------------------
# IDLE DETECTION
# ----------------------
def get_idle_minutes():
    """Get system idle time in minutes"""
    try:
        if OS == "Linux":
            return get_idle_minutes_linux()
        elif OS == "Windows":
            return get_idle_minutes_windows()
        elif OS == "Darwin":
            return get_idle_minutes_macos()
        else:
            logger.warning(f"Unsupported OS: {OS}")
            return 0
    except Exception as e:
        logger.error(f"Error getting idle time: {e}")
        return 0

# ----------------------
# POWER MANAGEMENT
# ----------------------
def sleep_system():
    """Put system to sleep"""
    if Config.DEMO_MODE:
        logger.info("[DEMO] Sleep action prevented - demo mode enabled")
        return True
    
    try:
        logger.info("Putting system to sleep...")
        if OS == "Linux":
            sleep_linux()
        elif OS == "Windows":
            sleep_windows()
        elif OS == "Darwin":
            sleep_macos()
        return True
    except Exception as e:
        logger.error(f"Failed to sleep system: {e}")
        return False

def hibernate_system():
    """Hibernate the system"""
    if Config.DEMO_MODE:
        logger.info("[DEMO] Hibernate action prevented - demo mode enabled")
        return True
    
    try:
        logger.info("Hibernating system...")
        if OS == "Linux":
            hibernate_linux()
        elif OS == "Windows":
            hibernate_windows()
        else:
            logger.warning("Hibernate not supported on this OS, using sleep instead")
            sleep_system()
        return True
    except Exception as e:
        logger.error(f"Failed to hibernate system: {e}")
        return False

# ----------------------
# SYSTEM INFORMATION
# ----------------------
def get_system_info():
    """Get detailed system information"""
    info = {
        'pc_id': platform.node(),
        'hostname': platform.node(),
        'os': OS,
        'os_version': platform.version(),
        'processor': platform.processor(),
        'agent_version': '2.0.0'
    }
    
    if HAS_PSUTIL:
        try:
            info['cpu_count'] = psutil.cpu_count()
            info['memory_gb'] = round(psutil.virtual_memory().total / (1024**3), 2)
        except:
            pass
    
    return info

def check_unsaved_work():
    """Check if there are applications with unsaved work"""
    if not Config.DETECT_UNSAVED_WORK or not HAS_PSUTIL:
        return False
    
    try:
        # Check for common applications that might have unsaved work
        critical_processes = ['word', 'excel', 'powerpoint', 'notepad', 'code', 'vim', 'emacs']
        
        for proc in psutil.process_iter(['name']):
            try:
                proc_name = proc.info['name'].lower()
                if any(app in proc_name for app in critical_processes):
                    logger.warning(f"Detected potentially unsaved work in: {proc.info['name']}")
                    return True
            except:
                continue
        
        return False
    except Exception as e:
        logger.error(f"Error checking for unsaved work: {e}")
        return False

# ----------------------
# SERVER COMMUNICATION
# ----------------------
class ServerClient:
    """Handle communication with GreenOps server"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': f'GreenOps-Agent/2.0 ({OS})'
        })
        
        if Config.API_KEY:
            self.session.headers.update({
                'Authorization': f'Bearer {Config.API_KEY}'
            })
    
    def send_report(self, data, retries=0):
        """Send activity report to server"""
        url = f"{Config.SERVER_URL}/api/v1/agent/report"
        
        try:
            response = self.session.post(url, json=data, timeout=10)
            response.raise_for_status()
            
            logger.debug(f"Report sent successfully: {data.get('action', 'NONE')}")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send report: {e}")
            
            if retries < Config.MAX_RETRIES:
                logger.info(f"Retrying in {Config.RETRY_DELAY} seconds... (attempt {retries + 1}/{Config.MAX_RETRIES})")
                time.sleep(Config.RETRY_DELAY)
                return self.send_report(data, retries + 1)
            
            return None
    
    def get_policy(self):
        """Fetch current policy from server"""
        url = f"{Config.SERVER_URL}/api/v1/agent/policy"
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            policy = response.json()
            logger.info(f"Policy fetched: idle_threshold={policy.get('idle_threshold')}min")
            return policy
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch policy: {e}")
            return None
    
    def check_health(self):
        """Check server health"""
        url = f"{Config.SERVER_URL}/health"
        
        try:
            response = self.session.get(url, timeout=5)
            response.raise_for_status()
            return True
        except:
            return False

# ----------------------
# POLICY EVALUATOR
# ----------------------
class PolicyEvaluator:
    """Evaluate power management policies"""
    
    def __init__(self):
        self.warning_start_time = None
        self.last_warning_shown = None
    
    def evaluate(self, idle_minutes, policy=None):
        """Evaluate what action should be taken"""
        # Use server policy or fallback to local config
        idle_threshold = policy.get('idle_threshold', Config.IDLE_THRESHOLD) if policy else Config.IDLE_THRESHOLD
        sleep_threshold = policy.get('sleep_threshold', Config.SLEEP_THRESHOLD) if policy else Config.SLEEP_THRESHOLD
        
        # Check if system is idle beyond sleep threshold
        if idle_minutes >= sleep_threshold:
            # Check for unsaved work
            if check_unsaved_work():
                logger.warning("Unsaved work detected, postponing sleep action")
                return 'NONE', 'Unsaved work detected'
            
            return 'SLEEP', f'Idle for {idle_minutes} minutes (threshold: {sleep_threshold})'
        
        # Check if system is idle beyond idle threshold (warning zone)
        elif idle_minutes >= idle_threshold:
            if Config.ENABLE_WARNINGS:
                self._show_warning(idle_minutes, sleep_threshold)
            return 'WARN', f'Approaching sleep threshold ({idle_minutes}/{sleep_threshold} min)'
        
        # System is active
        else:
            self.warning_start_time = None
            return 'NONE', 'System active'
    
    def _show_warning(self, idle_minutes, sleep_threshold):
        """Show warning to user"""
        now = datetime.now()
        
        # Only show warning every minute
        if self.last_warning_shown and (now - self.last_warning_shown).seconds < 60:
            return
        
        remaining = sleep_threshold - idle_minutes
        logger.warning(f"⚠️  System will sleep in {remaining} minutes if idle continues")
        
        # Platform-specific notification
        try:
            if OS == "Linux":
                os.system(f'notify-send "GreenOps" "System will sleep in {remaining} minutes"')
            elif OS == "Windows":
                # Windows notification would go here
                pass
            elif OS == "Darwin":
                os.system(f'osascript -e \'display notification "System will sleep in {remaining} minutes" with title "GreenOps"\'')
        except:
            pass
        
        self.last_warning_shown = now

# ----------------------
# STATISTICS TRACKER
# ----------------------
class StatsTracker:
    """Track agent statistics"""
    
    def __init__(self):
        self.stats_file = 'agent_stats.json'
        self.stats = self._load_stats()
    
    def _load_stats(self):
        """Load statistics from file"""
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        return {
            'total_checks': 0,
            'total_sleep_actions': 0,
            'total_hibernate_actions': 0,
            'total_idle_minutes': 0,
            'last_reset': datetime.now().isoformat(),
            'uptime_start': datetime.now().isoformat()
        }
    
    def _save_stats(self):
        """Save statistics to file"""
        try:
            with open(self.stats_file, 'w') as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save stats: {e}")
    
    def record_check(self, idle_minutes, action):
        """Record a check cycle"""
        self.stats['total_checks'] += 1
        self.stats['total_idle_minutes'] += idle_minutes
        
        if action == 'SLEEP':
            self.stats['total_sleep_actions'] += 1
        elif action == 'HIBERNATE':
            self.stats['total_hibernate_actions'] += 1
        
        self._save_stats()
    
    def get_summary(self):
        """Get statistics summary"""
        return self.stats

# ----------------------
# MAIN AGENT
# ----------------------
class GreenOpsAgent:
    """Main agent class"""
    
    def __init__(self):
        self.client = ServerClient()
        self.evaluator = PolicyEvaluator()
        self.stats = StatsTracker()
        self.system_info = get_system_info()
        self.policy = None
        self.policy_last_fetched = None
        
        logger.info(f"GreenOps Agent v2.0 starting on {OS}")
        logger.info(f"System: {self.system_info['pc_id']}")
        logger.info(f"Demo Mode: {Config.DEMO_MODE}")
    
    def start(self):
        """Start the agent main loop"""
        # Check server connectivity
        if not self.client.check_health():
            logger.warning("Server is not reachable. Will retry in background.")
        
        logger.info("Agent started successfully")
        logger.info(f"Monitoring interval: {Config.CHECK_INTERVAL} seconds")
        
        try:
            while True:
                self.run_cycle()
                time.sleep(Config.CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Agent stopped by user")
            self._print_stats()
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)
    
    def run_cycle(self):
        """Run one monitoring cycle"""
        try:
            # Fetch policy periodically (every 10 minutes)
            if not self.policy or not self.policy_last_fetched or \
               (datetime.now() - self.policy_last_fetched).seconds > 600:
                self.policy = self.client.get_policy()
                self.policy_last_fetched = datetime.now()
            
            # Get idle time
            idle_minutes = get_idle_minutes()
            
            # Evaluate policy
            action, reason = self.evaluator.evaluate(idle_minutes, self.policy)
            
            # Execute action
            if action == 'SLEEP':
                if sleep_system():
                    logger.info(f"System put to sleep: {reason}")
                else:
                    action = 'FAILED'
                    reason = 'Sleep action failed'
            
            # Prepare report data
            report_data = {
                **self.system_info,
                'idle_minutes': round(idle_minutes, 2),
                'action': action,
                'reason': reason,
                'threshold': self.policy.get('idle_threshold', Config.IDLE_THRESHOLD) if self.policy else Config.IDLE_THRESHOLD,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Send report to server
            self.client.send_report(report_data)
            
            # Track statistics
            self.stats.record_check(idle_minutes, action)
            
            # Log status
            status = f"Idle: {idle_minutes:.1f}min | Action: {action}"
            if action != 'NONE':
                logger.info(status)
            else:
                logger.debug(status)
                
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}", exc_info=True)
    
    def _print_stats(self):
        """Print agent statistics"""
        stats = self.stats.get_summary()
        logger.info("=" * 50)
        logger.info("Agent Statistics:")
        logger.info(f"  Total Checks: {stats['total_checks']}")
        logger.info(f"  Sleep Actions: {stats['total_sleep_actions']}")
        logger.info(f"  Total Idle Time: {stats['total_idle_minutes']:.1f} minutes")
        logger.info(f"  Uptime Since: {stats['uptime_start']}")
        logger.info("=" * 50)

# ----------------------
# ENTRY POINT
# ----------------------
def main():
    """Main entry point"""
    print("╔═══════════════════════════════════════╗")
    print("║     GreenOps Agent v2.0               ║")
    print("║  Carbon Governance System Monitor     ║")
    print("╚═══════════════════════════════════════╝")
    print()
    
    # Load configuration
    Config.load_from_file()
    
    # Create and start agent
    agent = GreenOpsAgent()
    agent.start()

if __name__ == '__main__':
    main()

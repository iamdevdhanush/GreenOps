import time
import platform
import requests

from idle_linux import get_idle_minutes_linux
from idle_windows import get_idle_minutes_windows
from power_linux import sleep_linux
from power_windows import sleep_windows

SERVER = "http://localhost:5000/agent/report"

SLEEP_AFTER = 15   # minutes
DEMO_MODE = True   # SAFE BY DEFAULT

OS = platform.system()

def get_idle_minutes():
    if OS == "Linux":
        return get_idle_minutes_linux()
    elif OS == "Windows":
        return get_idle_minutes_windows()
    return 0

def sleep_system():
    if DEMO_MODE:
        print("[DEMO] Sleep prevented")
        return

    if OS == "Linux":
        sleep_linux()
    elif OS == "Windows":
        sleep_windows()

while True:
    idle = get_idle_minutes()
    action = "NONE"

    if idle >= SLEEP_AFTER:
        action = "SLEEP"
        sleep_system()

    try:
        requests.post(SERVER, json={
            "pc_id": platform.node(),
            "os": OS,
            "idle_minutes": round(idle, 2),
            "action": action
        }, timeout=3)
    except:
        pass

    time.sleep(60)


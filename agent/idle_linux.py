import subprocess

def get_idle_minutes_linux():
    try:
        ms = int(subprocess.check_output(["xprintidle"]).decode())
        return ms / 1000 / 60
    except:
        return 0


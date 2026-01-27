import subprocess

def sleep_linux():
    subprocess.run(["systemctl", "suspend"])


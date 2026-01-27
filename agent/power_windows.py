import subprocess

def sleep_windows():
    subprocess.run(
        ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        shell=True
    )
import subprocess

def sleep_windows():
    subprocess.run(
        ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        shell=True
    )


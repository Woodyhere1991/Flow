"""One-shot ELEVATED setup: register Flow's watchdog to run with highest
privileges (so Windows lets it type into elevated/protected apps like Neo and
ZCode), restart Flow under that task, update the logon startup, and prove the
injection works by pasting a probe into the focused composer.
Everything lands in data/elevated_setup.log for the session record.
"""
import ctypes
import os
import subprocess
import sys
import time

sys.path.insert(0, r"C:\Users\wirih\repos\flow")
import wintext

REPO = r"C:\Users\wirih\repos\flow"
LOG = os.path.join(REPO, "data", "elevated_setup.log")
lines = []


def log(msg):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"{stamp} {msg}")


def is_elevated():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def flush():
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


log(f"setup started; elevated={is_elevated()} pid={os.getpid()}")
if not is_elevated():
    log("NOT ELEVATED - refusing to make changes")
    flush()
    sys.exit(1)

# 1. Kill any medium-integrity Flow instances.
out = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
     "'flow_watchdog|hotkey.py' -and $_.Name -match 'python' } | "
     "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; 'killed'"],
    capture_output=True, text=True)
log(f"killed old flow: {out.stdout.strip()}")

# 2. Register the highest-privilege logon task for the watchdog.
ps_reg = (
    "Register-ScheduledTask -TaskName 'FlowDictation' "
    "-Action (New-ScheduledTaskAction -Execute "
    f"'{REPO}\\venv\\Scripts\\pythonw.exe' -Argument '{REPO}\\flow_watchdog.py') "
    "-Principal (New-ScheduledTaskPrincipal -UserId $env:USERNAME "
    "-RunLevel Highest -LogonType Interactive) "
    "-Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
    "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 365)) "
    "-Force | Out-Null; 'task-registered'")
out = subprocess.run(["powershell", "-NoProfile", "-Command", ps_reg],
                     capture_output=True, text=True)
log(f"register task: {out.stdout.strip()} {out.stderr.strip()[:200]}")

# 3. Start Flow under the task NOW (elevated, no extra prompt).
out = subprocess.run(["schtasks", "/run", "/tn", "FlowDictation"],
                     capture_output=True, text=True)
log(f"task start: rc={out.returncode} {out.stdout.strip()} {out.stderr.strip()[:200]}")

# 4. Point the logon startup script at the task instead of direct python.
vbs_path = os.path.join(os.environ["APPDATA"],
                        "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup",
                        "Flow dictation watchdog.vbs")
try:
    with open(vbs_path, "w", encoding="utf-8") as f:
        f.write("' Starts the Flow dictation supervisor via its scheduled task\n"
                "' (highest privileges, so Flow may type into elevated apps).\n"
                "CreateObject(\"WScript.Shell\").Run "
                "\"schtasks /run /tn FlowDictation\", 0, False\n")
    log("startup vbs updated to trigger the task")
except Exception as e:
    log(f"startup vbs update FAILED: {e}")

# 5. Give Flow a moment, then prove elevated injection pastes into the
#    focused composer (ZCode's harness chat box was focused by the session).
time.sleep(4)
wintext.set_clipboard_text("elevated paste probe works")
time.sleep(0.2)
wintext.release_modifiers()
time.sleep(0.1)
ok = wintext.send_paste()
log(f"probe send_paste ok={ok}")
time.sleep(0.6)

log("setup complete")
flush()

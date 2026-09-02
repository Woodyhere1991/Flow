r"""
Supervises hotkey.py so that when something kills it, there is evidence.

hotkey.py already logs a graceful "Flow closed" line, and it catches every
exception it can see from the INSIDE (its own sys.excepthook and
threading.excepthook, set up in setup_logging()). None of that fires when
something ends the process from the outside - Task Manager "End Task", an
antivirus action, the system running low on memory, a stray `taskkill`.
Windows does not deliver anything to a process in that case, so hotkey.py
has no chance to write a line about its own death.

A supervisor sees it from the OUTSIDE instead. subprocess.Popen keeps a
handle to the child, and that handle can still read the exit code after the
child is gone - which is proof of what happened even when nothing inside
hotkey.py could have logged it.

Launch this instead of hotkey.py directly. It starts hotkey.py, waits, and
writes ONE line to flow_watchdog.log recording exactly when and how the
child stopped, and its best read on why. It does not restart hotkey.py -
that is deliberate, so today's exit reason is never overwritten by a
relaunch before there has been a chance to read it.
"""

import datetime
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PYTHONW = HERE / "venv" / "Scripts" / "pythonw.exe"
HOTKEY = HERE / "hotkey.py"

# Same folder hotkey.py already logs to, so both logs sit together.
import os
APP_DATA_DIR = pathlib.Path(os.environ.get(
    "LOCALAPPDATA", str(pathlib.Path.home() / "AppData" / "Local"))) / "Flow"
LOG_PATH = APP_DATA_DIR / "flow_watchdog.log"


def _verdict(code):
    """Best read on WHY the child stopped, from the exit code alone.

    A normal Python exit only ever returns a small non-negative number
    (hotkey.py's own __main__ returns 0 or calls sys.exit(1)). Windows
    reports a process that was terminated - TerminateProcess, a forced
    `taskkill /F`, or the system reclaiming it under memory pressure - as a
    LARGE or NEGATIVE code that Python did not choose, which is the
    fingerprint an external kill leaves behind.
    """
    if code == 0:
        return "normal exit (window closed or mainloop ended on its own)"
    if code == 1:
        return ("exit code 1 - check flow.log for a matching 'Flow could not "
                "start' entry at this time; if there isn't one, something "
                "else forced this exit code")
    if code is None:
        return "no exit code available"
    if code < 0 or code > 255:
        return (f"exit code {code} - not a code hotkey.py's own code ever "
                "returns, which means something OUTSIDE hotkey.py ended it "
                "(forced kill, logoff, or the system killing it for memory)")
    return f"exit code {code} - unexpected; hotkey.py does not return this"


def main():
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

    started = datetime.datetime.now()
    proc = subprocess.Popen([str(PYTHONW), str(HOTKEY)], cwd=str(HERE))
    proc.wait()
    ended = datetime.datetime.now()
    code = proc.returncode

    line = (f"{ended.strftime('%Y-%m-%d %H:%M:%S')}  "
            f"hotkey.py stopped after running {ended - started}  "
            f"exit_code={code}  -  {_verdict(code)}\n")

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


if __name__ == "__main__":
    main()

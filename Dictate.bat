@echo off
rem Launch the global dictation hotkey service via the watchdog, which
rem records how/when hotkey.py stops (see flow_watchdog.py). pythonw.exe =
rem no console window.
cd /d "%~dp0"
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0flow_watchdog.py"

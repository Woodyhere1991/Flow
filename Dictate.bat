@echo off
rem Launch the global dictation hotkey service. pythonw.exe = no console window.
cd /d "%~dp0"
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0hotkey.py"

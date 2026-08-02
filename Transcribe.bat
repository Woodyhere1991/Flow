@echo off
rem Launch the CrisperWhisper app. pythonw.exe = no console window.
cd /d "%~dp0"
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0app.py"

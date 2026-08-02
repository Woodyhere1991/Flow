@echo off
setlocal EnableExtensions
title Flow Setup

set "SETUP_DIR=%TEMP%\Flow-Setup-%RANDOM%%RANDOM%"
set "ZIP_PATH=%SETUP_DIR%\Flow.zip"
set "ZIP_URL=https://github.com/Woodyhere1991/Flow/archive/refs/heads/master.zip"

echo.
echo   Flow Setup
echo   ==========
echo.
echo   Downloading Flow...
mkdir "%SETUP_DIR%" >nul 2>nul

curl.exe --location --fail --silent --show-error --output "%ZIP_PATH%" "%ZIP_URL%"
if errorlevel 1 goto :download_failed

echo   Starting the installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Expand-Archive -LiteralPath '%ZIP_PATH%' -DestinationPath '%SETUP_DIR%' -Force; exit 0 } catch { Write-Host $_; exit 1 }"
if errorlevel 1 goto :download_failed

call "%SETUP_DIR%\Flow-master\setup.bat" %*
exit /b %errorlevel%

:download_failed
echo.
echo   Flow could not be downloaded. Check your internet connection and try again.
echo.
if not defined FLOW_NO_PAUSE pause
exit /b 1

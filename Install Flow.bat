@echo off
title Install Flow
cd /d "%~dp0"
call "%~dp0setup.bat" %*
exit /b %errorlevel%

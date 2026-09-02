@echo off
setlocal EnableExtensions
set "SOURCE_DIR=%~dp0"
set "SOURCE_DIR_TRIMMED=%SOURCE_DIR:~0,-1%"
rem Install location can be overridden by presetting FLOW_INSTALL_DIR (no
rem trailing backslash) - e.g. to install in place inside a checkout.
if defined FLOW_INSTALL_DIR (
  set "APP_DIR=%FLOW_INSTALL_DIR%"
) else (
  set "APP_DIR=%LOCALAPPDATA%\Flow\app"
)
cd /d "%SOURCE_DIR%"

echo.
echo   Flow installer
echo   ==============
echo.
echo   This installs Flow and creates a Flow shortcut on your Desktop.
echo   You only need to run it once.
echo.

if /i "%~1"=="--check" (
  echo   Installer check passed.
  exit /b 0
)

set "INSTALLER_MODE="
set "ALLOW_SLOW="
if /i "%~1"=="--installed" set "INSTALLER_MODE=1"
if /i "%~2"=="--installed" set "INSTALLER_MODE=1"
if /i "%~1"=="--allow-slow" set "ALLOW_SLOW=1"
if /i "%~2"=="--allow-slow" set "ALLOW_SLOW=1"

rem ---- choose the fastest supported hardware path before large downloads ----
set "HAS_NVIDIA="
where nvidia-smi >nul 2>nul
if not errorlevel 1 set "HAS_NVIDIA=1"
rem Inno Setup is a 32-bit process, so System32 can be redirected to SysWOW64.
rem Sysnative reliably exposes the real 64-bit NVIDIA utility in that case.
if exist "%SystemRoot%\System32\nvidia-smi.exe" set "HAS_NVIDIA=1"
if exist "%SystemRoot%\Sysnative\nvidia-smi.exe" set "HAS_NVIDIA=1"
if defined FLOW_TEST_FORCE_CPU set "HAS_NVIDIA="

set "FLOW_DEFAULT_MODEL=small"
if defined HAS_NVIDIA set "FLOW_DEFAULT_MODEL=turbo"

if not defined HAS_NVIDIA (
  echo   IMPORTANT HARDWARE WARNING
  echo   --------------------------
  echo   This PC has no supported NVIDIA graphics card.
  echo   Flow will use its smallest speech model, but it may still be slow.
  echo   On older PCs it may take a long time after every recording and may
  echo   not be useful.
  echo.
  if not defined ALLOW_SLOW (
    if defined INSTALLER_MODE exit /b 3
    choice /C YN /N /M "Continue with the slower CPU version? [Y/N] "
    if errorlevel 2 exit /b 3
  )
)

rem ---- keep the running app in a permanent local folder ---------------------
echo   [1/7] Preparing Flow...
if /i "%SOURCE_DIR_TRIMMED%"=="%APP_DIR%" goto :copy_done
if not exist "%APP_DIR%" mkdir "%APP_DIR%"
rem %SOURCE_DIR% ends in a backslash; inside quotes that escapes the closing
rem quote (\"), merging every argument into one and failing robocopy. Use the
rem trimmed form, which has no trailing backslash.
robocopy "%SOURCE_DIR_TRIMMED%" "%APP_DIR%" /E /R:1 /W:1 /XD venv .git __pycache__ /XF settings.json *.wav *.mp3 *.m4a >nul
if errorlevel 8 goto :fail
:copy_done
cd /d "%APP_DIR%"

rem ---- find or install Python ------------------------------------------------
set "PY_CMD="
set "PY_ARGS="

where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    set "PY_CMD=py"
    set "PY_ARGS=-3.12"
  )
)

if not defined PY_CMD (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  )
)

if not defined PY_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
  )
)

if not defined PY_CMD (
  echo   Python is needed. Installing Python 3.12 now...
  echo.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo   Windows App Installer is missing, so Python could not be installed.
    echo   Install Python 3.12 from https://www.python.org/downloads/
    echo   then run Install Flow again.
    echo.
    if not defined INSTALLER_MODE pause
    exit /b 1
  )
  winget install --id Python.Python.3.12 --exact --scope user ^
    --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto :fail
  set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)

"%PY_CMD%" %PY_ARGS% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>nul
if errorlevel 1 (
  echo   Python 3.10 or newer is required.
  if not defined INSTALLER_MODE pause
  exit /b 1
)

echo   [2/7] Creating the virtual environment...
if not exist venv (
  "%PY_CMD%" %PY_ARGS% -m venv venv
  if errorlevel 1 goto :fail
) else (
  echo         already exists, reusing it
)

set VPY=venv\Scripts\python.exe

echo   [3/7] Updating pip...
"%VPY%" -m pip install --quiet --upgrade pip
if errorlevel 1 goto :fail

rem ---- torch -----------------------------------------------------------------
echo   [4/7] Installing the best AI engine for this PC...
if not defined HAS_NVIDIA (
  echo         No NVIDIA GPU detected - installing the CPU build.
  "%VPY%" -m pip install torch==2.6.0 torchaudio==2.6.0
) else (
  echo         NVIDIA GPU detected - installing the CUDA build.
  "%VPY%" -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
)
if errorlevel 1 goto :fail

echo   [5/7] Verifying the hardware choice...
if defined HAS_NVIDIA (
  "%VPY%" hardware_profile.py --expected-nvidia
  if errorlevel 1 goto :gpu_fail
) else (
  "%VPY%" hardware_profile.py --force-device cpu
  if errorlevel 1 goto :fail
)
set "FLOW_DEFAULT_MODEL="
set /p FLOW_DEFAULT_MODEL=<"%LOCALAPPDATA%\Flow\recommended_model.txt"
if /i not "%FLOW_DEFAULT_MODEL%"=="small" if /i not "%FLOW_DEFAULT_MODEL%"=="turbo" if /i not "%FLOW_DEFAULT_MODEL%"=="large" set "FLOW_DEFAULT_MODEL="
if not defined FLOW_DEFAULT_MODEL goto :fail

echo   [6/7] Installing everything else...
rem Keep third-party packages from replacing the matching CUDA/CPU PyTorch pair.
"%VPY%" -m pip install -r requirements.txt --constraint constraints.txt
if errorlevel 1 goto :fail

echo   [7/7] Downloading the recommended speech model for offline use...
"%VPY%" prepare_offline.py --model "%FLOW_DEFAULT_MODEL%"
if errorlevel 1 goto :fail

rem ---- icon + shortcut -------------------------------------------------------
if not exist icon.ico "%VPY%" make_icon.py

echo.
echo   Creating a Desktop shortcut...
powershell -NoProfile -Command ^
  "$w=New-Object -ComObject WScript.Shell;" ^
  "$s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Flow.lnk');" ^
  "$s.TargetPath='%CD%\venv\Scripts\pythonw.exe';" ^
  "$s.Arguments='\"%CD%\flow_watchdog.py\"';" ^
  "$s.WorkingDirectory='%CD%';" ^
  "$s.IconLocation='%CD%\icon.ico';" ^
  "$s.Save()"

echo.
echo   Done. Launch "Flow" from your Desktop.
echo.
echo   Setup has downloaded everything needed for normal offline dictation.
echo.
if defined HAS_NVIDIA (
  echo   Flow is optimized for this PC's NVIDIA graphics card.
) else (
  echo   Flow is using the smallest model because this PC will run on its CPU.
)
echo.
if not defined INSTALLER_MODE pause
exit /b 0

:gpu_fail
echo.
echo   Flow found an NVIDIA graphics card, but could not enable it.
echo   Setup stopped instead of silently installing a very slow version.
if not defined INSTALLER_MODE pause
exit /b 4

:fail
echo.
echo   Setup failed - see the messages above.
if not defined INSTALLER_MODE pause
exit /b 1

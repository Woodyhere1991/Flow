@echo off
setlocal EnableExtensions
set "SOURCE_DIR=%~dp0"
set "SOURCE_DIR_TRIMMED=%SOURCE_DIR:~0,-1%"
set "APP_DIR=%LOCALAPPDATA%\Flow\app"
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

rem ---- keep the running app in a permanent local folder ---------------------
echo   [1/6] Preparing Flow...
if /i "%SOURCE_DIR_TRIMMED%"=="%APP_DIR%" goto :copy_done
if not exist "%APP_DIR%" mkdir "%APP_DIR%"
robocopy "%SOURCE_DIR%" "%APP_DIR%" /E /R:1 /W:1 /XD venv .git __pycache__ /XF settings.json *.wav *.mp3 *.m4a >nul
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
    pause
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
  pause
  exit /b 1
)

echo   [2/6] Creating the virtual environment...
if not exist venv (
  "%PY_CMD%" %PY_ARGS% -m venv venv
  if errorlevel 1 goto :fail
) else (
  echo         already exists, reusing it
)

set VPY=venv\Scripts\python.exe

echo   [3/6] Updating pip...
"%VPY%" -m pip install --quiet --upgrade pip
if errorlevel 1 goto :fail

rem ---- torch -----------------------------------------------------------------
echo   [4/6] Installing PyTorch ^(about 2.5 GB, this takes a while^)...
where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo         No NVIDIA GPU detected - installing the CPU build.
  echo         Flow will still work, but transcription will be much slower.
  "%VPY%" -m pip install torch torchaudio
) else (
  echo         NVIDIA GPU detected - installing the CUDA build.
  "%VPY%" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
)
if errorlevel 1 goto :fail

echo   [5/6] Installing everything else...
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo   [6/6] Downloading the speech model for offline use...
"%VPY%" prepare_offline.py
if errorlevel 1 goto :fail

rem ---- icon + shortcut -------------------------------------------------------
if not exist icon.ico "%VPY%" make_icon.py

echo.
echo   Creating a Desktop shortcut...
powershell -NoProfile -Command ^
  "$w=New-Object -ComObject WScript.Shell;" ^
  "$s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Flow.lnk');" ^
  "$s.TargetPath='%CD%\venv\Scripts\pythonw.exe';" ^
  "$s.Arguments='\"%CD%\hotkey.py\"';" ^
  "$s.WorkingDirectory='%CD%';" ^
  "$s.IconLocation='%CD%\icon.ico';" ^
  "$s.Save()"

echo.
echo   Done. Launch "Flow" from your Desktop.
echo.
echo   Setup has downloaded everything needed for normal offline dictation.
echo.
if /i not "%~1"=="--installed" pause
exit /b 0

:fail
echo.
echo   Setup failed - see the messages above.
if /i not "%~1"=="--installed" pause
exit /b 1

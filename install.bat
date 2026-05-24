@echo off
setlocal

cd /d "%~dp0"

echo ============================================
echo  Voice Task Board - Install
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    echo Install Python 3.11+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js / npm is not installed or not on PATH.
    echo Install Node.js 18+ from https://nodejs.org/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating Python virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo [1/4] Virtual environment already exists, skipping.
)

echo [2/4] Installing Python dependencies...
call .venv\Scripts\activate.bat
pip install --quiet -e ".[dev]"
if errorlevel 1 goto :fail

if not exist "frontend\node_modules" (
    echo [3/4] Installing frontend dependencies...
    pushd frontend
    call npm install
    popd
    if errorlevel 1 goto :fail
) else (
    echo [3/4] Frontend dependencies already installed, skipping.
)

echo [4/4] Building application...
powershell -ExecutionPolicy Bypass -File ".\build.ps1"
if errorlevel 1 goto :fail

echo.
echo ============================================
echo  Build complete!
echo ============================================
echo.

if exist "installer\output\VoiceTaskBoardSetup.exe" (
    echo Launching installer...
    start "" "installer\output\VoiceTaskBoardSetup.exe"
) else if exist "installer\dist\VoiceTaskBoard\VoiceTaskBoard.exe" (
    echo Inno Setup not found - launching app directly.
    echo To create a real installer, install Inno Setup 6 from:
    echo   https://jrsoftware.org/isdl.php
    echo then re-run this script.
    echo.
    start "" "installer\dist\VoiceTaskBoard\VoiceTaskBoard.exe"
) else (
    echo [ERROR] Build finished but no output found.
    pause
    exit /b 1
)

exit /b 0

:fail
echo.
echo [ERROR] Install failed. See messages above.
pause
exit /b 1

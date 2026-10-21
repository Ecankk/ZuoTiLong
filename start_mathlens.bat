@echo off
setlocal
title MathLens Launcher
cd /d "%~dp0"

if not exist "server.py" (
  echo [MathLens] Cannot find server.py.
  echo Please run this file from the MathLens project folder.
  pause
  exit /b 1
)

curl --silent --fail http://127.0.0.1:4173/api/health >nul 2>&1
if %errorlevel%==0 (
  echo [MathLens] Server is already running. Opening the browser...
  goto open_browser
)

where py >nul 2>&1
if %errorlevel%==0 goto use_py

where python >nul 2>&1
if %errorlevel%==0 goto use_python

echo [MathLens] Python 3.11 or newer is required.
echo Install Python from https://www.python.org/downloads/
pause
exit /b 1

:use_py
echo [MathLens] Starting local server with Python launcher...
start "MathLens Server" /D "%~dp0" cmd /k py -3 server.py --host 127.0.0.1 --port 4173
goto open_browser

:use_python
echo [MathLens] Starting local server with Python...
start "MathLens Server" /D "%~dp0" cmd /k python server.py --host 127.0.0.1 --port 4173

:open_browser
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:4173/"
echo [MathLens] Browser opened. Keep the MathLens Server window running.
endlocal

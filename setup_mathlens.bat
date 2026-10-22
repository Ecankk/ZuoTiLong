@echo off
setlocal
cd /d "%~dp0"
set "MATHLENS_PY=python"
python -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,13)" >nul 2>&1
if not errorlevel 1 goto create_env
set "MATHLENS_PY=py -3.12"
py -3.12 -c "import sys; assert sys.version_info[:2] == (3,12)" >nul 2>&1
if not errorlevel 1 goto create_env
echo Install Python 3.12, then run this setup again.
pause
exit /b 1
:create_env
if exist ".venv\Scripts\python.exe" goto install_dependencies
%MATHLENS_PY% -m venv .venv
if errorlevel 1 goto failed
:install_dependencies
%MATHLENS_PY% -m pip --python ".venv\Scripts\python.exe" install -r requirements-ocr.txt
if errorlevel 1 goto failed
echo Setup complete. Double-click start_mathlens.bat.
pause
exit /b 0
:failed
echo Setup failed. Keep this output for troubleshooting.
pause
exit /b 1

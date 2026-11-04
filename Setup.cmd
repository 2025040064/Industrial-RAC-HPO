@echo off
setlocal
cd /d "%~dp0"
set "UV_CACHE_DIR=%CD%\.cache\uv"
set "UV_PYTHON_INSTALL_DIR=%CD%\.python"
set "TMP=%CD%\.cache\tmp"
set "TEMP=%CD%\.cache\tmp"
if not exist "%TMP%" mkdir "%TMP%"
uv sync --frozen --extra test
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -S scripts\configure_environment.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m rac_hpo fetch
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\verify_environment.py

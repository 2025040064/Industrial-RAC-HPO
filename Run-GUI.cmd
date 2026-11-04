@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Missing project virtual environment. Run Setup.cmd first.
  pause
  exit /b 1
)
set "MPLCONFIGDIR=%CD%\.cache\matplotlib"
start "RAC-HPO" ".venv\Scripts\pythonw.exe" main.py

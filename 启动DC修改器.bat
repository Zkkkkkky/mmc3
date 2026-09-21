@echo off
setlocal
cd /d "%~dp0"
if exist "output\app\新DC篇完整修改器.exe" (
  start "" "output\app\新DC篇完整修改器.exe"
  exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
  echo 尚未创建项目虚拟环境。
  echo 请先执行 python -m venv .venv
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "tools\run_dc_modifier.py"
if errorlevel 1 pause

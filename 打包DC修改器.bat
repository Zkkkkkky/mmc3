@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

set "PAUSE_ON_EXIT=1"
if /i "%~1"=="--no-pause" set "PAUSE_ON_EXIT=0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv\Scripts\python.exe.
  echo Create the virtual environment and install development dependencies first.
  if "%PAUSE_ON_EXIT%"=="1" pause
  exit /b 1
)

if not exist "tools\build_modifier_exe.ps1" (
  echo [ERROR] Missing tools\build_modifier_exe.ps1.
  if "%PAUSE_ON_EXIT%"=="1" pause
  exit /b 1
)

echo Building the DC modifier executable...
echo.
where pwsh.exe >nul 2>nul
if errorlevel 1 goto use_windows_powershell

pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\tools\build_modifier_exe.ps1"
goto build_finished

:use_windows_powershell
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\tools\build_modifier_exe.ps1"

:build_finished
set "BUILD_EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%BUILD_EXIT_CODE%"=="0" (
  echo [ERROR] Packaging failed with exit code %BUILD_EXIT_CODE%.
  if "%PAUSE_ON_EXIT%"=="1" pause
  exit /b %BUILD_EXIT_CODE%
)

echo [OK] Packaging finished. See output\app.
if "%PAUSE_ON_EXIT%"=="1" pause
exit /b 0

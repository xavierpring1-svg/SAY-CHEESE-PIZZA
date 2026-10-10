@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0runtime\python.exe" (
  "%~dp0runtime\python.exe" "%~dp0check_desktop.py"
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Extract the complete Windows release or install 64-bit Python 3.12.
    pause
    exit /b 1
  )
  py -3.12 "%~dp0check_desktop.py"
)
set "diagnostic_exit=%ERRORLEVEL%"
pause
exit /b %diagnostic_exit%

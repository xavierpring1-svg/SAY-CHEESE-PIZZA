@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0runtime\pythonw.exe" (
  start "" "%~dp0runtime\pythonw.exe" "%~dp0main.py"
  exit /b 0
)
echo Download the Windows release ZIP containing the bundled runtime.
echo For source development use: python -m pip install -r requirements.txt
echo Then: python main.py
pause
exit /b 1

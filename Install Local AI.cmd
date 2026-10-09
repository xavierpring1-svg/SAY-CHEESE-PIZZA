@echo off
setlocal
title JARVIS - Local AI Setup
echo This installs Ollama for private conversation on your PC.
echo The llama3.2 model downloads about 2 GB and needs around 8 GB RAM.
echo.
where ollama >nul 2>nul
if errorlevel 1 (
  winget install --id Ollama.Ollama --exact --scope user --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto failed
)
set "JARVIS_OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%JARVIS_OLLAMA%" set "JARVIS_OLLAMA=ollama"
"%JARVIS_OLLAMA%" pull llama3.2
if errorlevel 1 goto failed
echo.
echo Done. In JARVIS Settings choose Ollama (local), model llama3.2, and Save.
pause
exit /b 0
:failed
echo.
echo Setup could not finish. Install Ollama from https://ollama.com/download/windows
echo Then run: ollama pull llama3.2
pause
exit /b 1

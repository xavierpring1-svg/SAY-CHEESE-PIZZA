@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -Command "$root=(Get-Location).Path; $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'JARVIS.lnk')); $s.TargetPath=Join-Path $root 'JARVIS.exe'; $s.WorkingDirectory=$root; $s.IconLocation=Join-Path $root 'jarvis.ico'; $s.Save()"
if errorlevel 1 (
  echo Could not create the shortcut. You can still run JARVIS.exe or Start JARVIS.cmd.
  pause
  exit /b 1
)
echo Desktop shortcut created.
pause

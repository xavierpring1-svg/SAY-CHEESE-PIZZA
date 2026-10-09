$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktop 'JARVIS.lnk'))
if (Test-Path (Join-Path $root 'JARVIS.exe')) {
    $shortcut.TargetPath = Join-Path $root 'JARVIS.exe'
} else {
    $shortcut.TargetPath = Join-Path $root 'runtime\pythonw.exe'
    $shortcut.Arguments = '"' + (Join-Path $root 'main.py') + '"'
}
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = Join-Path $root 'jarvis.ico'
$shortcut.Description = 'JARVIS personal desktop assistant'
$shortcut.Save()
Write-Host 'JARVIS shortcut created on your desktop. Keep the extracted folder in place.'

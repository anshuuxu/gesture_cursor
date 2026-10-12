$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher = Join-Path $ProjectDir "Launch_Gesture_Cursor.bat"
if (-not (Test-Path $Launcher)) {
    throw "Launch_Gesture_Cursor.bat was not found in $ProjectDir"
}
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Gesture Cursor.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Launcher
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.Description = "Launch Gesture Cursor and choose a camera"
$Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll, 220"
$Shortcut.Save()
Write-Host "Desktop shortcut created: $ShortcutPath"

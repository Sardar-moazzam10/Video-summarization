# restart_backends.ps1
# This script stops all backend services and restarts them with updated code

Write-Host "Stopping all Python backend processes..." -ForegroundColor Yellow

# Stop all Python processes (more aggressive approach)
Get-Process -Name "python*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# Also close any PowerShell windows that might be running backends
$currentPID = $PID
Get-Process -Name "powershell*" -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne $currentPID } | ForEach-Object {
    $windowTitle = $_.MainWindowTitle
    if ($windowTitle -like "*Backend*" -or $windowTitle -like "*Port*") {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}

# Wait for processes to fully stop
Start-Sleep -Seconds 3

Write-Host "Clearing Python cache..." -ForegroundColor Cyan
Get-ChildItem -Path . -Include "__pycache__" -Recurse -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Include "*.pyc" -Recurse -Force | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "Python cache cleared!" -ForegroundColor Green
Write-Host ""
Write-Host "Now starting all backends with updated code..." -ForegroundColor Cyan
Write-Host ""

# Run the start script
& .\run_all_backends.ps1

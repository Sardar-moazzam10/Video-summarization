# run_all_backends.ps1
# This script starts all backend services for the YouTube Search App in separate windows.

$PYTHON_EXE = ".\.venv\Scripts\python.exe"

Write-Host "🚀 Starting all backend services..." -ForegroundColor Cyan

# 1. Auth Backend (Port 5000)
Write-Host "✅ Starting Auth Backend on port 5000..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Auth Backend (Port 5000)'; $PYTHON_EXE auth_backend.py"

# 2. Transcript Backend (Port 5001)
Write-Host "✅ Starting Transcript Backend on port 5001..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Transcript Backend (Port 5001)'; $PYTHON_EXE transcript_backend.py"

# 3. Merge Backend (Port 5002)
Write-Host "✅ Starting Merge Backend on port 5002..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Merge Backend (Port 5002)'; $PYTHON_EXE merge_backend.py"

# 4. Proxy Server (Port 8080)
Write-Host "✅ Starting Proxy Server on port 8080..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Proxy Server (Port 8080)'; node server.js"

Write-Host "🎉 All backends are starting! Keep these windows open." -ForegroundColor Yellow
Write-Host "Your frontend should already be running on http://localhost:3000" -ForegroundColor Cyan

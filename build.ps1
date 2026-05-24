#!/usr/bin/env pwsh

Write-Host "Building Voice Task Board..."

# Step 1: Build frontend
Write-Host "Step 1: Building frontend..."
Push-Location frontend
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Error "Frontend build failed"
    exit 1
}
Pop-Location

# Step 2: Run PyInstaller
Write-Host "Step 2: Running PyInstaller..."
.\.venv\Scripts\pyinstaller.exe pyinstaller.spec --distpath installer\dist --workpath installer\build
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed"
    exit 1
}

# Step 3: Run Inno Setup (if iscc.exe is available)
Write-Host "Step 3: Creating installer with Inno Setup..."
$iscPath = "C:\Program Files (x86)\Inno Setup 6\iscc.exe"
if (Test-Path $iscPath) {
    & $iscPath installer\voice-task-board.iss
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Inno Setup failed"
        exit 1
    }
    Write-Host "Installer created: installer\output\VoiceTaskBoardSetup.exe"
} else {
    Write-Warning "Inno Setup not found. Skipping installer creation."
    Write-Host "You can manually run: iscc.exe installer\voice-task-board.iss"
}

Write-Host "Build complete!"

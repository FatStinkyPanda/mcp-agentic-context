# Usage: .\install.ps1
# Bootstraps Python 3.12 + ML dependencies on a fresh machine.

$root = $PSScriptRoot
$pythonInstaller = Join-Path $root "python\python-3.12.8-amd64.exe"
$wheelsDir = Join-Path $root "cu121-py312"
$reqFile = Join-Path $root "requirements.txt"

# Step 1: Check if Python 3.12 is already installed
$python312 = Get-Command "py" -ErrorAction SilentlyContinue
$has312 = $false
if ($python312) {
    $versions = & py -0 2>&1
    if ($versions -match "3\.12") {
        $has312 = $true
        Write-Host "Python 3.12 is already installed."
    }
}

if (-not $has312) {
    Write-Host "Installing Python 3.12.8..."
    Start-Process -FilePath $pythonInstaller -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0" -Wait
    Write-Host "Python 3.12.8 installed. You may need to restart your terminal."
    Write-Host "Re-run this script after restarting if pip can't find python."
    exit
}

# Step 2: Create a venv with Python 3.12
$venvPath = Join-Path (Get-Location) ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "Creating .venv with Python 3.12..."
    & py -3.12 -m venv $venvPath
}

# Step 3: Activate and install dependencies
Write-Host "Activating venv and installing dependencies from $wheelsDir..."
& "$venvPath\Scripts\Activate.ps1"
pip install --no-index --find-links $wheelsDir -r $reqFile

Write-Host "Setup complete! Venv is active. Test with: python -c `"import torch; print(torch.cuda.is_available())`""
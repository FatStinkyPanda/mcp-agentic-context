# Usage: .\install.ps1
# Bootstraps Python + Web Development dependencies.

$root = $PSScriptRoot
$reqFile = Join-Path $root "requirements.txt"
$wheelsDir = Join-Path $root "wheels"

# Step 1: Detect Python
$pythonCmd = $null
if (Get-Command "py" -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
} elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command "python3" -ErrorAction SilentlyContinue) {
    $pythonCmd = "python3"
}

if (-not $pythonCmd) {
    Write-Error "Python is not installed. Please install Python 3.8+ before running this script."
    exit 1
}

# Step 2: Create a venv
$venvPath = Join-Path (Get-Location) ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "Creating .venv..."
    if ($pythonCmd -eq "py") {
        & py -m venv $venvPath
    } else {
        & $pythonCmd -m venv $venvPath
    }
}

# Step 3: Activate and install dependencies
Write-Host "Activating venv and installing Web Development dependencies..."
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
& $activateScript

# Upgrade pip
python -m pip install --upgrade pip

if (Test-Path $wheelsDir) {
    Write-Host "Installing from local wheels..."
    pip install --no-index --find-links $wheelsDir -r $reqFile
} else {
    Write-Host "Local wheels not found. Installing from online PyPI..."
    pip install -r $reqFile
}

Write-Host "Setup complete! Venv is active."

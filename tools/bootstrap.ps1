param(
    [switch]$Dev,
    [switch]$Recreate,
    [string]$PythonCommand = $env:DIVAPPLY_PYTHON,
    [string]$VenvDir = ".venv"
)

$ErrorActionPreference = "Stop"

function Resolve-PythonCommand {
    param([string]$Preferred)

    if ($Preferred) {
        return [pscustomobject]@{
            Command = $Preferred
            Args    = @()
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return [pscustomobject]@{
            Command = "python"
            Args    = @()
        }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return [pscustomobject]@{
            Command = "py"
            Args    = @("-3")
        }
    }

    throw "No Python interpreter found. Install Python 3.11+ or set DIVAPPLY_PYTHON to a full interpreter path."
}

function Invoke-Python {
    param(
        [pscustomobject]$Spec,
        [string[]]$Args
    )

    $allArgs = @()
    $allArgs += $Spec.Args
    $allArgs += $Args
    & $Spec.Command @allArgs
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$pythonCmd = Resolve-PythonCommand -Preferred $PythonCommand
$venvPath = Join-Path $repoRoot $VenvDir
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if ($Recreate -and (Test-Path $venvPath)) {
    Remove-Item -Recurse -Force $venvPath
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment at $venvPath ..."
    Invoke-Python -Spec $pythonCmd -Args @("-m", "venv", $venvPath)
}

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment creation failed: $venvPython was not created."
}

Write-Host "Checking Python build compatibility ..."
try {
    & $venvPython -c "import tomllib"
    & $venvPython -c "import email.headerregistry"
} catch {
    throw "This Python build is missing standard library modules needed for packaging. Install the official Python 3.11+ release from python.org, then rerun tools\bootstrap.ps1."
}

Write-Host "Upgrading pip ..."
& $venvPython -m pip install --upgrade pip setuptools wheel

if ($Dev) {
    Write-Host "Installing DivApply with pip install -e .[dev] ..."
    & $venvPython -m pip install -e ".[dev]"
} else {
    Write-Host "Installing DivApply with pip install . ..."
    & $venvPython -m pip install .
}

Write-Host ""
Write-Host "Running DivApply doctor ..."
& $venvPython -m divapply doctor

Write-Host ""
Write-Host "Bootstrap complete."
Write-Host "Activate the environment with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "Then run:"
Write-Host "  divapply init"

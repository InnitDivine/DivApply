param(
    [switch]$SkipAudit,
    [switch]$SkipDocker,
    [string]$PythonCommand = "python",
    [string]$ImageTag = "divapply:preflight"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed"
    }
}

Invoke-Step "Ruff" { & $PythonCommand -m ruff check . }
Invoke-Step "Pytest" { & $PythonCommand -m pytest -q }
Invoke-Step "Build package" {
    & $PythonCommand -m pip install --upgrade build twine
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $PythonCommand -m build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $PythonCommand -m twine check dist/*
}

if (-not $SkipAudit) {
    Invoke-Step "Dependency audit" { & $PythonCommand -m pip_audit --progress-spinner off }
}

if (-not $SkipDocker) {
    Invoke-Step "Docker build" { docker build -t $ImageTag . }
    Invoke-Step "Docker smoke test" { docker run --rm $ImageTag selfcheck }
}

Write-Host ""
Write-Host "Preflight checks passed." -ForegroundColor Green

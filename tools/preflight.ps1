param(
    [switch]$SkipAudit,
    [switch]$SkipDocker,
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

Invoke-Step "Validate Python lock" { uv lock --check }
Invoke-Step "Sync locked toolchain" { uv sync --locked --extra dev --extra full }
Invoke-Step "Ruff" { uv run --locked ruff check . }
Invoke-Step "Mypy (Linux)" { uv run --locked mypy --platform linux src/divapply }
Invoke-Step "Mypy (Windows)" { uv run --locked mypy --platform win32 src/divapply }
Invoke-Step "Pytest with branch coverage" {
    uv run --locked coverage erase
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    uv run --locked coverage run -m pytest -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    uv run --locked coverage report
}
Invoke-Step "Build package" {
    uv run --locked python -m build --no-isolation
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    uv run --locked python -m twine check dist/*
}
Invoke-Step "Release SBOM and checksums" {
    uv run --locked python tools/build_release_evidence.py --dist-dir dist --out-dir release
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    uv run --locked python tools/build_release_evidence.py --out-dir release --verify
}

$privateProfile = Join-Path $env:USERPROFILE ".divapply/profile.json"
if (Test-Path -LiteralPath $privateProfile) {
    Invoke-Step "Private-value collision scan" {
        uv run --locked python tools/check_private_collisions.py --root $repoRoot --profile $privateProfile --dist-dir (Join-Path $repoRoot "dist")
    }
}

if (-not $SkipAudit) {
    Invoke-Step "Python environment audit" { uv run --locked pip-audit --progress-spinner off }
    Invoke-Step "Python project audit" { uv run --locked python -m pip_audit . --progress-spinner off }
    Invoke-Step "Locked MCP dependency audit" {
        Push-Location (Join-Path $repoRoot "src/divapply/mcp_runtime_assets")
        try {
            npm audit --omit=dev --audit-level=high
        }
        finally {
            Pop-Location
        }
    }
}

if (-not $SkipDocker) {
    Invoke-Step "Docker build" { docker build -t $ImageTag . }
    Invoke-Step "Docker smoke test" { docker run --rm $ImageTag selfcheck }
}

Write-Host ""
Write-Host "Preflight checks passed." -ForegroundColor Green

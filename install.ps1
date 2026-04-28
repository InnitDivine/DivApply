param(
    [switch]$Dev,
    [switch]$Recreate,
    [switch]$SkipJobSpy,
    [switch]$SkipBrowsers,
    [switch]$SkipDoctor,
    [switch]$Init,
    [string]$Browsers = "chromium,firefox",
    [string]$PythonCommand = $env:DIVAPPLY_PYTHON,
    [string]$VenvDir = ".venv"
)

$ErrorActionPreference = "Stop"

$bootstrap = Join-Path $PSScriptRoot "tools\bootstrap.ps1"
if (-not (Test-Path $bootstrap)) {
    throw "Could not find $bootstrap. Run install.ps1 from the DivApply repository root."
}

& $bootstrap @PSBoundParameters

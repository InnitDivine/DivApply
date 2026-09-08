param(
    [switch]$Help,
    [switch]$Dev,
    [switch]$Recreate,
    [switch]$SkipJobSpy,
    [switch]$SkipBrowsers,
    [switch]$SkipDoctor,
    [switch]$Init,
    [string]$Browsers = "chromium",
    [string]$PythonCommand = $env:DIVAPPLY_PYTHON,
    [string]$VenvDir = ".venv"
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Write-Host @"
DivApply installer

Usage:
  install
  install -Dev
  install -Init
  install -Recreate
  install -SkipBrowsers
  install -SkipJobSpy
  install -Browsers all

Options:
  -Dev             Install editable development dependencies.
  -Recreate        Delete and recreate the virtual environment.
  -SkipJobSpy      Skip python-jobspy install.
  -SkipBrowsers    Skip Playwright browser downloads.
  -SkipDoctor      Skip divapply doctor after install.
  -Init            Run the interactive divapply init wizard.
  -PythonCommand   Python interpreter to use. Python 3.12 recommended; JobSpy needs 3.11 or 3.12.
                   Python 3.13/3.14 may fail with python-jobspy/numpy pins.
  -VenvDir         Virtual environment directory inside this repository. Default: .venv
  -Browsers        chromium, firefox, webkit, all, or none.
"@
    exit 0
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-SoftWarning {
    param([string]$Message)
    Write-Host "WARN: $Message" -ForegroundColor Yellow
}

function Test-PythonCommand {
    param(
        [Parameter(Mandatory = $true)][pscustomobject]$Spec,
        [switch]$RequireJobSpyCompatible
    )

    $probe = if ($RequireJobSpyCompatible) {
        "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)"
    } else {
        "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    }
    $allArgs = @()
    $allArgs += $Spec.Args
    $allArgs += @("-c", $probe)

    try {
        & $Spec.Command @allArgs *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Resolve-PythonCommand {
    param(
        [string]$Preferred,
        [switch]$RequireJobSpyCompatible
    )

    if ($Preferred) {
        $preferredSpec = [pscustomobject]@{
            Command = $Preferred
            Args    = @()
        }
        if (Test-PythonCommand -Spec $preferredSpec -RequireJobSpyCompatible:$RequireJobSpyCompatible) {
            return $preferredSpec
        }
        throw "Requested Python interpreter is missing or incompatible: $Preferred"
    }

    $candidates = @()
    $localPython312 = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Programs\Python\Python312\python.exe"
    if (Test-Path -LiteralPath $localPython312 -PathType Leaf) {
        $candidates += [pscustomobject]@{
            Command = $localPython312
            Args    = @()
        }
    }

    $python312 = Get-Command python3.12 -ErrorAction SilentlyContinue
    if ($python312) {
        $candidates += [pscustomobject]@{
            Command = $python312.Source
            Args    = @()
        }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += [pscustomobject]@{
            Command = $py.Source
            Args    = @("-3.12")
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += [pscustomobject]@{
            Command = $python.Source
            Args    = @()
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonCommand -Spec $candidate -RequireJobSpyCompatible:$RequireJobSpyCompatible) {
            return $candidate
        }
    }

    $requiredVersion = if ($RequireJobSpyCompatible) { "Python 3.11 or 3.12" } else { "Python 3.11+" }
    throw "No usable $requiredVersion interpreter found. Install Python 3.12 or set DIVAPPLY_PYTHON to a full interpreter path."
}

function Install-UserLauncher {
    param([Parameter(Mandatory = $true)][string]$VenvPython)

    if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
        return $null
    }

    $launcherDir = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Microsoft\WindowsApps"
    New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null
    $launcherPath = Join-Path $launcherDir "divapply.cmd"
    $launcherText = @"
@echo off
if not exist "$VenvPython" (
  echo DivApply environment not found at $VenvPython 1>&2
  echo Re-run the DivApply installer to repair it. 1>&2
  exit /b 1
)
"$VenvPython" -m divapply %*
"@
    [IO.File]::WriteAllText($launcherPath, $launcherText, [Text.Encoding]::ASCII)
    return $launcherPath
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
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Args -join ' ')"
    }
}

function Invoke-VenvPython {
    param([string[]]$Args)

    & $script:VenvPython @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: python $($Args -join ' ')"
    }
}

function Invoke-VenvPythonOptional {
    param(
        [string[]]$Args,
        [string]$Warning
    )

    & $script:VenvPython @Args
    if ($LASTEXITCODE -ne 0) {
        Write-SoftWarning $Warning
        return $false
    }
    return $true
}

function Resolve-BrowserList {
    param([string]$BrowserSpec)

    $items = @()
    foreach ($raw in $BrowserSpec.Split(",")) {
        $browser = $raw.Trim().ToLowerInvariant()
        if (-not $browser) {
            continue
        }
        if ($browser -eq "none") {
            return @()
        }
        if ($browser -eq "all") {
            return @("chromium", "firefox", "webkit")
        }
        if ($browser -notin @("chromium", "firefox", "webkit")) {
            throw "Unsupported Playwright browser '$browser'. Use chromium, firefox, webkit, all, or none."
        }
        $items += $browser
    }
    return $items
}

function Copy-IfMissing {
    param(
        [string]$Source,
        [string]$Target
    )

    if ((Test-Path $Source) -and -not (Test-Path $Target)) {
        Copy-Item -LiteralPath $Source -Destination $Target
        Write-Host "Created $Target"
    }
}

function Assert-SafeVenvPath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Candidate
    )

    $trimChars = [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $repoFull = [IO.Path]::GetFullPath($RepoRoot).TrimEnd($trimChars)
    $candidateFull = if ([IO.Path]::IsPathRooted($Candidate)) {
        [IO.Path]::GetFullPath($Candidate)
    } else {
        [IO.Path]::GetFullPath((Join-Path $repoFull $Candidate))
    }
    $prefix = $repoFull + [IO.Path]::DirectorySeparatorChar
    if (-not $candidateFull.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing virtual environment outside repository: $candidateFull"
    }

    $cursor = $candidateFull
    while ($cursor.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -Force -LiteralPath $cursor
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing virtual environment outside repository via link: $candidateFull"
            }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) {
            break
        }
        $cursor = $parent.FullName
    }
    return $candidateFull
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$requireJobSpyCompatible = -not $SkipJobSpy
$pythonCmd = Resolve-PythonCommand `
    -Preferred $PythonCommand `
    -RequireJobSpyCompatible:$requireJobSpyCompatible
$venvPath = Assert-SafeVenvPath -RepoRoot $repoRoot -Candidate $VenvDir
$script:VenvPython = Join-Path $venvPath "Scripts\python.exe"

Write-Host "DivApply installer" -ForegroundColor Green
Write-Host "Repository: $repoRoot"

if ($Recreate -and (Test-Path $venvPath)) {
    Write-Step "Recreating virtual environment"
    Remove-Item -Recurse -Force -LiteralPath $venvPath
} elseif (Test-Path $venvPath) {
    $venvSpec = [pscustomobject]@{
        Command = $script:VenvPython
        Args    = @()
    }
    if (-not (Test-PythonCommand -Spec $venvSpec -RequireJobSpyCompatible:$requireJobSpyCompatible)) {
        Write-Step "Rebuilding unusable virtual environment at $venvPath"
        Remove-Item -Recurse -Force -LiteralPath $venvPath
    }
}

if (-not (Test-Path $script:VenvPython)) {
    Write-Step "Creating virtual environment at $venvPath"
    Invoke-Python -Spec $pythonCmd -Args @("-m", "venv", $venvPath)
}

if (-not (Test-Path $script:VenvPython)) {
    throw "Virtual environment creation failed: $script:VenvPython was not created."
}

Write-Step "Checking Python version"
Invoke-VenvPython -Args @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 'DivApply requires Python 3.11+')")

if (-not $SkipJobSpy) {
    Invoke-VenvPython -Args @("-c", "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 'Full JobSpy setup requires Python 3.11 or 3.12 because python-jobspy pins numpy==1.26.3. Use Python 3.12, set DIVAPPLY_PYTHON, pass -PythonCommand, or rerun with -SkipJobSpy.')")
}

try {
    Invoke-VenvPython -Args @("-c", "import tomllib; import email.headerregistry")
} catch {
    throw "This Python build is missing standard library modules needed for packaging. Install the official Python 3.11+ release from python.org, then rerun install.ps1."
}

Write-Step "Upgrading pip"
Invoke-VenvPython -Args @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")

if ($Dev) {
    Write-Step "Installing DivApply in editable development mode"
    Invoke-VenvPython -Args @("-m", "pip", "install", "-e", ".[dev,full]")
} else {
    Write-Step "Installing DivApply"
    Invoke-VenvPython -Args @("-m", "pip", "install", ".[full]")
}

if (-not $SkipJobSpy) {
    Write-Step "Installing python-jobspy"
    Invoke-VenvPython -Args @("-m", "pip", "install", "--no-deps", "https://files.pythonhosted.org/packages/d5/2b/18863fcd3c544a69d81e351381a50036a33c21b61cc1c6de2a8f25931237/python_jobspy-1.1.82-py3-none-any.whl#sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9")
    Invoke-VenvPython -Args @("-m", "divapply.jobspy_runtime")
} else {
    Write-SoftWarning "Skipped python-jobspy. Discovery will miss major job boards until you install it."
}

if (-not $SkipBrowsers) {
    $browserList = Resolve-BrowserList -BrowserSpec $Browsers
    if ($browserList.Count -gt 0) {
        Write-Step "Installing Playwright browsers: $($browserList -join ', ')"
        $ok = Invoke-VenvPythonOptional `
            -Args (@("-m", "playwright", "install") + $browserList) `
            -Warning "Playwright browser download failed. You can rerun: .\install.ps1 -Browsers `"$Browsers`""
        if (-not $ok) {
            Write-SoftWarning "PDF export and default auto-apply need chromium."
        }
    }
}

Write-Step "Preparing ~/.divapply"
Invoke-VenvPython -Args @("-c", "from divapply.config import ensure_dirs; ensure_dirs()")

$userProfile = [Environment]::GetFolderPath("UserProfile")
$appDir = Join-Path $userProfile ".divapply"
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
Copy-IfMissing -Source (Join-Path $repoRoot ".env.example") -Target (Join-Path $appDir ".env")
Copy-IfMissing -Source (Join-Path $repoRoot "profile.example.json") -Target (Join-Path $appDir "profile.example.json")
Copy-IfMissing -Source (Join-Path $repoRoot "src\divapply\config\searches.example.yaml") -Target (Join-Path $appDir "searches.yaml")

Write-Step "Installing the per-user divapply command"
$launcherPath = Install-UserLauncher -VenvPython $script:VenvPython
if ($launcherPath) {
    Write-Host "Installed $launcherPath"
}

if ($Init) {
    Write-Step "Running first-time setup wizard"
    Invoke-VenvPython -Args @("-m", "divapply", "init")
}

if (-not $SkipDoctor) {
    Write-Step "Running DivApply doctor"
    Invoke-VenvPythonOptional -Args @("-m", "divapply", "doctor") -Warning "Doctor reported setup issues. Read the output above, then rerun divapply doctor after fixing them." | Out-Null
}

Write-Host ""
Write-Host "DivApply install complete." -ForegroundColor Green
Write-Host ""
Write-Host "Use it from any new terminal with:"
Write-Host "  divapply doctor"
Write-Host ""
Write-Host "First-time setup:"
Write-Host "  divapply init"
Write-Host ""
Write-Host "For auto-apply, install Node.js 20+ plus Codex CLI or Claude Code, then rerun:"
Write-Host "  divapply doctor"

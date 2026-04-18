param(
    [Parameter(Mandatory = $true)]
    [string[]]$InputPath,

    [string]$OutputDir
)

$ErrorActionPreference = "Stop"

if (-not $OutputDir) {
    $baseDir = if ($PSScriptRoot) { $PSScriptRoot } else { Get-Location }
    $OutputDir = Join-Path $baseDir "transcript_text"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$word = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false

    foreach ($path in $InputPath) {
        if (-not (Test-Path $path)) {
            Write-Error "File not found: $path"
        }

        $doc = $null
        try {
            $doc = $word.Documents.Open($path, $false, $true)
            $outPath = Join-Path $OutputDir ([System.IO.Path]::GetFileNameWithoutExtension($path) + ".txt")
            $doc.SaveAs([ref]$outPath, [ref]2)
            Write-Output $outPath
        } finally {
            if ($doc) {
                $doc.Close()
            }
        }
    }
} finally {
    if ($word) {
        $word.Quit()
    }
}

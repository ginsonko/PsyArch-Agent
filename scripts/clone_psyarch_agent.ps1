param(
    [string] $TargetDir = "",
    [string] $RepoUrl = "https://github.com/ginsonko/PsyArch-Agent.git",
    [switch] $DryRun
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

function Write-PA {
    param([string] $Message)
    Write-Host "[PA] $Message"
}

function Resolve-Target {
    param([string] $PathValue)
    $base = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        $PathValue = Join-Path $base "PsyArch-Agent"
    }
    $expanded = [Environment]::ExpandEnvironmentVariables($PathValue.Trim().Trim('"'))
    if ([System.IO.Path]::IsPathRooted($expanded)) {
        return [System.IO.Path]::GetFullPath($expanded)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $base $expanded))
}

$target = Resolve-Target $TargetDir
Write-PA "Repository: $RepoUrl"
Write-PA "Target directory: $target"
if ($DryRun) {
    Write-PA "Dry-run enabled. No files will be changed."
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found on PATH. Please install Git for Windows first."
}

if (Test-Path -LiteralPath $target -PathType Container) {
    if (-not (Test-Path -LiteralPath (Join-Path $target ".git") -PathType Container)) {
        throw "Target exists but is not a Git checkout: $target"
    }
    Push-Location $target
    try {
        $origin = (& git remote get-url origin 2>$null)
        Write-PA "Existing checkout detected. origin=$origin"
        if ($DryRun) {
            Write-PA "Would run: git pull --ff-only"
        } else {
            & git pull --ff-only
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    } finally {
        Pop-Location
    }
} else {
    $parent = Split-Path -Parent $target
    if ($DryRun) {
        Write-PA "Would create: $parent"
        Write-PA "Would run: git clone $RepoUrl $target"
    } else {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        & git clone $RepoUrl $target
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}

Write-PA "Done."


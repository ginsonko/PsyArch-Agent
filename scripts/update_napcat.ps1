param(
    [string] $NapCatDir = "",
    [string] $RepoUrl = "https://github.com/NapNeko/NapCatQQ.git",
    [switch] $DryRun
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

function Write-PA {
    param([string] $Message)
    Write-Host "[PA] $Message"
}

function Resolve-AbsolutePath {
    param([string] $PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    $expanded = [Environment]::ExpandEnvironmentVariables($PathValue.Trim().Trim('"'))
    if ([System.IO.Path]::IsPathRooted($expanded)) {
        return [System.IO.Path]::GetFullPath($expanded)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $expanded))
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($NapCatDir)) {
    $NapCatDir = Join-Path (Split-Path -Parent $repoRoot) "NapCatQQ"
}
$targetDir = Resolve-AbsolutePath $NapCatDir

Write-PA "NapCat repository: $RepoUrl"
Write-PA "Target directory: $targetDir"
if ($DryRun) {
    Write-PA "Dry-run enabled. No files will be changed."
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found on PATH. Please install Git for Windows first."
}

if (Test-Path -LiteralPath $targetDir -PathType Container) {
    $gitDir = Join-Path $targetDir ".git"
    if (-not (Test-Path -LiteralPath $gitDir -PathType Container)) {
        throw "Target directory already exists but is not a Git checkout: $targetDir"
    }

    Write-PA "Existing NapCat checkout detected."
    Push-Location $targetDir
    try {
        $currentUrl = (& git remote get-url origin 2>$null)
        Write-PA "origin: $currentUrl"
        if ($DryRun) {
            Write-PA "Would run: git fetch --prune origin"
            Write-PA "Would run: git pull --ff-only origin current-branch"
        } else {
            & git fetch --prune origin
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            & git pull --ff-only
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    } finally {
        Pop-Location
    }
} else {
    $parent = Split-Path -Parent $targetDir
    if ($DryRun) {
        Write-PA "Would create: $parent"
        Write-PA "Would run: git clone $RepoUrl $targetDir"
    } else {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        & git clone $RepoUrl $targetDir
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}

if (-not $DryRun) {
    if (Get-Command corepack -ErrorAction SilentlyContinue) {
        Write-PA "Enabling corepack for pnpm if available..."
        try {
            & corepack enable
        } catch {
            Write-PA "corepack enable skipped: $($_.Exception.Message)"
        }
    }
    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue) -and -not (Get-Command pnpm.cmd -ErrorAction SilentlyContinue)) {
        Write-PA "WARN: pnpm was not found. NapCat source launcher may install/build only after pnpm is available."
    }
}

Write-PA "Done."


param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $NapCatArgs
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

function Write-PA {
    param([string] $Message)
    Write-Host "[PA] $Message"
}

function Add-Candidate {
    param(
        [System.Collections.Generic.List[string]] $List,
        [string] $Value
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return
    }
    $trimmed = [Environment]::ExpandEnvironmentVariables($Value.Trim().Trim('"'))
    if ($trimmed -match '^[A-Za-z]:$') {
        $trimmed = "$trimmed\"
    }
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        return
    }
    $List.Add($trimmed)
}

function Resolve-QQBaseDir {
    $candidates = [System.Collections.Generic.List[string]]::new()

    Add-Candidate $candidates $env:NAPCAT_QQ_BASE_DIR
    Add-Candidate $candidates $env:QQ_BASE_DIR

    $regPaths = @(
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ'
    )
    foreach ($regPath in $regPaths) {
        try {
            $qq = Get-ItemProperty -Path $regPath -ErrorAction Stop
            if ($qq.UninstallString) {
                Add-Candidate $candidates (Split-Path -Parent ($qq.UninstallString.Trim().Trim('"')))
            }
            if ($qq.DisplayIcon) {
                $icon = (($qq.DisplayIcon -split ',')[0]).Trim().Trim('"')
                Add-Candidate $candidates (Split-Path -Parent $icon)
            }
        } catch {
            # Keep probing common locations below.
        }
    }

    Add-Candidate $candidates (Split-Path -Qualifier $PSScriptRoot)
    foreach ($root in @('H:\', 'D:\', 'C:\')) {
        Add-Candidate $candidates $root
    }
    foreach ($drive in [System.IO.DriveInfo]::GetDrives()) {
        if ($drive.DriveType -eq [System.IO.DriveType]::Fixed) {
            Add-Candidate $candidates $drive.RootDirectory.FullName
        }
    }
    foreach ($path in @(
        'C:\Program Files\Tencent\QQNT',
        'C:\Program Files (x86)\Tencent\QQNT',
        'C:\Program Files\Tencent\QQ',
        'C:\Program Files (x86)\Tencent\QQ'
    )) {
        Add-Candidate $candidates $path
    }

    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($candidate in $candidates) {
        $probe = $candidate
        if (Test-Path -LiteralPath $probe -PathType Leaf) {
            $probe = Split-Path -Parent $probe
        }
        if (-not $seen.Add($probe)) {
            continue
        }
        if (Test-Path -LiteralPath (Join-Path $probe 'versions') -PathType Container) {
            return (Resolve-Path -LiteralPath $probe).Path
        }
    }
    throw 'Cannot locate QQ base directory. Set NAPCAT_QQ_BASE_DIR to the directory that contains the versions folder, for example H:\.'
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$napcatDir = Join-Path (Split-Path -Parent $repoRoot) 'NapCatQQ'
$loaderDir = Join-Path $napcatDir 'packages\napcat-shell-loader'
$devDir = Join-Path $napcatDir 'packages\napcat-develop'
$shellDist = Join-Path $napcatDir 'packages\napcat-shell\dist'
$webuiDist = Join-Path $napcatDir 'packages\napcat-webui-frontend\dist'
$shellStaticIndex = Join-Path $shellDist 'static\index.html'
$win10Launcher = Join-Path $loaderDir 'launcher-win10.bat'
$defaultLauncher = Join-Path $loaderDir 'launcher.bat'
$loaderMain = Join-Path $loaderDir 'napcat.mjs'
$shellMain = Join-Path $shellDist 'napcat.mjs'
$devLoader = Join-Path $devDir 'loadNapCat.cjs'
$oneBotSrc = Join-Path $devDir 'config\onebot11.json'
$oneBotDevDist = Join-Path $devDir 'dist\config\onebot11.json'
$oneBotShellDist = Join-Path $shellDist 'config\onebot11.json'

Write-PA 'NapCat one-click launcher'
Write-PA "NapCat directory: $napcatDir"
Write-PA 'WebUI: http://127.0.0.1:6099/webui/'
Write-PA 'OneBot HTTP API: http://127.0.0.1:3000/'
Write-PA 'PA webhook should be: http://127.0.0.1:8765/api/agent/napcat/event'
Write-Host ''

if (Test-Path -LiteralPath $loaderMain -PathType Leaf) {
    if (Test-Path -LiteralPath $win10Launcher -PathType Leaf) {
        Write-PA 'Release shell-loader detected.'
        Push-Location $loaderDir
        try {
            & $win10Launcher @NapCatArgs
            exit $LASTEXITCODE
        } finally {
            Pop-Location
        }
    }
    if (Test-Path -LiteralPath $defaultLauncher -PathType Leaf) {
        Write-PA 'Release shell-loader detected.'
        Push-Location $loaderDir
        try {
            & $defaultLauncher @NapCatArgs
            exit $LASTEXITCODE
        } finally {
            Pop-Location
        }
    }
}

if (-not (Test-Path -LiteralPath $devLoader -PathType Leaf)) {
    Write-PA 'ERROR: Neither release shell-loader nor source develop loader was found.'
    Write-PA "Missing: $loaderMain"
    Write-PA "Missing: $devLoader"
    Write-PA 'Run 一键拉取或更新NapCat.bat first.'
    exit 1
}

$qqBaseDir = Resolve-QQBaseDir
Write-PA "QQ base directory: $qqBaseDir"
Write-PA 'Source checkout detected. Preparing NapCat shell dist if needed.'

Push-Location $napcatDir
try {
    if (-not (Test-Path -LiteralPath (Join-Path $napcatDir 'node_modules') -PathType Container)) {
        Write-PA 'node_modules missing, running pnpm install...'
        & pnpm.cmd install
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    $webuiIndex = Join-Path $webuiDist 'index.html'
    if (-not (Test-Path -LiteralPath $webuiIndex -PathType Leaf)) {
        Write-PA "$webuiIndex missing, building napcat-webui-frontend..."
        & pnpm.cmd --filter napcat-webui-frontend run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    if (-not (Test-Path -LiteralPath $shellMain -PathType Leaf) -or -not (Test-Path -LiteralPath $shellStaticIndex -PathType Leaf)) {
        Write-PA 'napcat-shell dist is incomplete, building napcat-shell...'
        & pnpm.cmd --filter napcat-shell run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    if (Test-Path -LiteralPath $oneBotSrc -PathType Leaf) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $oneBotDevDist) | Out-Null
        Copy-Item -LiteralPath $oneBotSrc -Destination $oneBotDevDist -Force
        if (Test-Path -LiteralPath $shellDist -PathType Container) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $oneBotShellDist) | Out-Null
            Copy-Item -LiteralPath $oneBotSrc -Destination $oneBotShellDist -Force
        }
    }
} finally {
    Pop-Location
}

Write-PA 'Starting NapCat develop loader...'
Push-Location $devDir
try {
    & node.exe '.\loadNapCat.cjs' $qqBaseDir
    exit $LASTEXITCODE
} finally {
    Pop-Location
}


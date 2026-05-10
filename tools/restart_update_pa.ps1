param(
  [string]$Root = "",
  [string]$Repo = "https://github.com/ginsonko/PsyArch-Agent.git",
  [string]$Branch = "main",
  [int]$Port = 8765,
  [switch]$NoBrowser,
  [switch]$DryRun
)

$ErrorActionPreference = "Continue"

function Write-PA {
  param([string]$Message)
  Write-Host "[PA] $Message"
}

function Resolve-RepoRoot {
  param([string]$Path)
  if (-not [string]::IsNullOrWhiteSpace($Path)) {
    return (Resolve-Path -LiteralPath $Path).Path
  }
  $scriptDir = Split-Path -Parent $PSCommandPath
  return (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
}

function Test-RepoLike {
  param([string]$Path)
  return (Test-Path -LiteralPath (Join-Path $Path "observatory\_web.py")) -and
    (Test-Path -LiteralPath (Join-Path $Path "observatory")) -and
    (Test-Path -LiteralPath (Join-Path $Path "hdb"))
}

function Find-PortPids {
  param([int]$LocalPort)
  $pids = [System.Collections.Generic.HashSet[int]]::new()
  $connections = @()
  try {
    $connections = Get-NetTCPConnection -LocalPort $LocalPort -ErrorAction Stop |
      Where-Object { $_.State -in @("Listen", "Established", "Bound") -or $_.State -eq $null }
  } catch {
    $connections = @()
  }
  foreach ($conn in $connections) {
    if ($conn.OwningProcess -and [int]$conn.OwningProcess -gt 0) {
      [void]$pids.Add([int]$conn.OwningProcess)
    }
  }
  if ($pids.Count -gt 0) {
    return @($pids)
  }

  try {
    $lines = & netstat -ano -p tcp 2>$null | Select-String -Pattern (":$LocalPort\s")
    foreach ($line in $lines) {
      $parts = ($line.Line -split "\s+") | Where-Object { $_ -ne "" }
      if ($parts.Count -ge 5) {
        $pidValue = 0
        if ([int]::TryParse($parts[-1], [ref]$pidValue) -and $pidValue -gt 0) {
          [void]$pids.Add($pidValue)
        }
      }
    }
  } catch {
    # Best effort only.
  }
  return @($pids | ForEach-Object { [int]$_ })
}

function Stop-PortProcess {
  param([int]$LocalPort)
  $pids = @(Find-PortPids $LocalPort) | Sort-Object -Unique
  if ($pids.Count -eq 0) {
    Write-PA "No process is listening on port $LocalPort."
    return
  }

  foreach ($pidValue in $pids) {
    if ($pidValue -eq $PID) {
      continue
    }
    $label = "pid=$pidValue"
    try {
      $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
      if ($procInfo) {
        $label = "pid=$pidValue name=$($procInfo.Name) cmd=$($procInfo.CommandLine)"
      }
    } catch {
      try {
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($proc) {
          $label = "pid=$pidValue name=$($proc.ProcessName)"
        }
      } catch {
        # Keep pid label.
      }
    }
    Write-PA "Stopping process on port ${LocalPort}: $label"
    try {
      Stop-Process -Id $pidValue -Force -ErrorAction Stop
    } catch {
      Write-PA "WARN: failed to stop pid=$pidValue : $($_.Exception.Message)"
    }
  }

  Start-Sleep -Seconds 2
}

function Invoke-GitUpdate {
  param(
    [string]$RootPath,
    [string]$RepoUrl,
    [string]$BranchName
  )
  $git = Get-Command git -ErrorAction SilentlyContinue
  if (-not $git) {
    Write-PA "WARN: Git was not found. Skip update and start local copy."
    return $false
  }

  Push-Location $RootPath
  try {
    Write-PA "Updating current folder by Git: $RootPath"
    & git remote get-url origin *> $null
    if ($LASTEXITCODE -ne 0) {
      & git remote add origin $RepoUrl
    }
    & git remote set-url origin $RepoUrl
    & git fetch origin $BranchName
    if ($LASTEXITCODE -ne 0) {
      Write-PA "WARN: git fetch failed."
      return $false
    }

    & git show-ref --verify --quiet "refs/heads/$BranchName"
    if ($LASTEXITCODE -ne 0) {
      & git checkout -b $BranchName "origin/$BranchName"
    } else {
      & git checkout $BranchName
    }
    if ($LASTEXITCODE -ne 0) {
      Write-PA "WARN: git checkout failed."
      return $false
    }

    & git branch "--set-upstream-to=origin/$BranchName" $BranchName *> $null
    & git pull --ff-only origin $BranchName
    if ($LASTEXITCODE -ne 0) {
      Write-PA "WARN: git pull failed."
      return $false
    }
    Write-PA "Git update finished."
    return $true
  } finally {
    Pop-Location
  }
}

function Copy-LatestRepoIntoZipFolder {
  param(
    [string]$RootPath,
    [string]$RepoUrl,
    [string]$BranchName
  )
  $git = Get-Command git -ErrorAction SilentlyContinue
  if (-not $git) {
    Write-PA "WARN: Git was not found. Cannot download latest source for ZIP-style folder."
    return $false
  }

  $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pa-agent-update-{0}" -f ([guid]::NewGuid().ToString("N")))
  $tempRepo = Join-Path $tempRoot "PsyArch-Agent"
  try {
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    Write-PA "Current folder has no .git. Downloading latest source to a temporary folder..."
    & git clone --depth 1 --branch $BranchName $RepoUrl $tempRepo
    if ($LASTEXITCODE -ne 0) {
      Write-PA "WARN: temporary git clone failed."
      return $false
    }

    $excludeDirs = @(
      ".git",
      ".venv",
      "venv",
      "env",
      "node_modules",
      "__pycache__",
      ".pytest_cache",
      "observatory\outputs",
      "observatory\frontend\node_modules",
      "observatory\frontend\dist",
      "hdb\data",
      "hdb\logs",
      "NapCatQQ",
      "reports",
      "local_notes"
    )
    $excludeFiles = @(
      ".env",
      ".env.*",
      "*.log",
      "*.jsonl",
      "*.secret",
      "*.secrets"
    )

    $args = @(
      $tempRepo,
      $RootPath,
      "/E",
      "/R:2",
      "/W:1",
      "/NFL",
      "/NDL",
      "/NP"
    )
    foreach ($dir in $excludeDirs) {
      $args += "/XD"
      $args += (Join-Path $RootPath $dir)
      $args += (Join-Path $tempRepo $dir)
    }
    foreach ($file in $excludeFiles) {
      $args += "/XF"
      $args += $file
    }

    Write-PA "Copying latest source into current folder while keeping runtime data..."
    & robocopy @args
    $code = $LASTEXITCODE
    if ($code -le 7) {
      Write-PA "Source copy update finished. robocopy code=$code"
      $global:LASTEXITCODE = 0
      return $true
    }
    Write-PA "WARN: robocopy failed with code=$code"
    return $false
  } finally {
    try {
      if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
      }
    } catch {
      # Best effort cleanup.
    }
  }
}

function Update-CurrentFolder {
  param(
    [string]$RootPath,
    [string]$RepoUrl,
    [string]$BranchName
  )
  if (Test-Path -LiteralPath (Join-Path $RootPath ".git")) {
    $ok = Invoke-GitUpdate -RootPath $RootPath -RepoUrl $RepoUrl -BranchName $BranchName
    if ($ok) {
      return $true
    }
    Write-PA "Git update did not complete. The backend will still restart with the current files."
    return $false
  }
  return Copy-LatestRepoIntoZipFolder -RootPath $RootPath -RepoUrl $RepoUrl -BranchName $BranchName
}

function Resolve-PythonCommand {
  param([string]$RootPath)
  $venvPython = Join-Path $RootPath ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $venvPython) {
    return @{ Command = $venvPython; Args = @() }
  }
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    return @{ Command = $py.Source; Args = @("-3") }
  }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return @{ Command = $python.Source; Args = @() }
  }
  return $null
}

function Start-PA {
  param(
    [string]$RootPath,
    [int]$LocalPort,
    [switch]$SkipBrowser
  )
  $python = Resolve-PythonCommand $RootPath
  if (-not $python) {
    Write-PA "ERROR: Python 3.10+ was not found. Please run dependency installer after installing Python."
    return $false
  }

  $args = @()
  $args += $python.Args
  $args += @("-m", "observatory", "--mode", "web", "--no-browser", "--host", "127.0.0.1", "--port", [string]$LocalPort)

  Write-PA "Starting PA-Agent + AP backend..."
  Write-PA ("Python: {0} {1}" -f $python.Command, ($python.Args -join " "))
  $cmdLine = "`"$($python.Command)`" $($args -join " ")"
  Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", $cmdLine) -WorkingDirectory $RootPath -WindowStyle Normal

  Start-Sleep -Seconds 5
  if (-not $SkipBrowser) {
    Start-Process ("http://127.0.0.1:{0}/next/" -f $LocalPort)
  }
  return $true
}

$rootPath = Resolve-RepoRoot $Root
Write-Host "======================================"
Write-Host "  PsyArch-Agent restart and update"
Write-Host "======================================"
Write-Host "Folder : $rootPath"
Write-Host "Repo   : $Repo"
Write-Host "Branch : $Branch"
Write-Host "Port   : $Port"
if ($DryRun) {
  Write-Host "Mode   : dry run"
}
Write-Host ""

if (-not (Test-RepoLike $rootPath)) {
  Write-PA "ERROR: This script must be placed in the PsyArch-Agent folder."
  Write-PA "Missing observatory/_web.py or hdb directory."
  exit 1
}

if ($DryRun) {
  Write-PA "Dry run: repo root verified. No process will be stopped, updated, or started."
  if (Test-Path -LiteralPath (Join-Path $rootPath ".git")) {
    Write-PA "Dry run: this folder is Git-managed and will update in place from origin/$Branch."
  } else {
    Write-PA "Dry run: this folder has no .git; it will download latest source and copy it over while preserving runtime data."
  }
  exit 0
}

Stop-PortProcess -LocalPort $Port
$updated = Update-CurrentFolder -RootPath $rootPath -RepoUrl $Repo -BranchName $Branch
Write-Host ""
if ($updated) {
  Write-PA "Update step completed."
} else {
  Write-PA "Update step was skipped or failed. Restarting with the files currently in this folder."
}

$started = Start-PA -RootPath $rootPath -LocalPort $Port -SkipBrowser:$NoBrowser
if ($started) {
  Write-PA "Done. Open: http://127.0.0.1:$Port/next/"
  Write-PA "If the browser still shows the old page, press Ctrl+F5."
} else {
  Write-PA "Restart failed."
  exit 1
}

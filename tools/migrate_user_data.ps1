param(
  [string]$Root = "",
  [string]$Source = "",
  [switch]$Preview,
  [switch]$IncludeLogs
)

$ErrorActionPreference = "Stop"

function Resolve-ExistingPath {
  param([string]$Path)
  return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-RepoRoot {
  param([string]$Path)
  if (-not [string]::IsNullOrWhiteSpace($Path)) {
    return Resolve-ExistingPath $Path
  }
  $scriptDir = Split-Path -Parent $PSCommandPath
  return Resolve-ExistingPath (Join-Path $scriptDir "..")
}

function Test-RepoLike {
  param([string]$Path)
  return (Test-Path -LiteralPath (Join-Path $Path "observatory")) -and
    (Test-Path -LiteralPath (Join-Path $Path "hdb"))
}

function Test-HasMigratableData {
  param([string]$Path)
  return (Test-Path -LiteralPath (Join-Path $Path "observatory\outputs\agent")) -or
    (Test-Path -LiteralPath (Join-Path $Path "observatory\outputs\auto_tuner")) -or
    (Test-Path -LiteralPath (Join-Path $Path "hdb\data"))
}

function Normalize-FullPath {
  param([string]$Path)
  return [System.IO.Path]::GetFullPath($Path).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
}

function Is-UnderRoot {
  param(
    [string]$RootPath,
    [string]$TargetPath
  )
  $rootFull = Normalize-FullPath $RootPath
  $targetFull = Normalize-FullPath $TargetPath
  return $targetFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -or
    $targetFull.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase) -or
    $targetFull.StartsWith($rootFull + [System.IO.Path]::AltDirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-UnderRoot {
  param(
    [string]$RootPath,
    [string]$TargetPath
  )
  if (-not (Is-UnderRoot $RootPath $TargetPath)) {
    throw "unsafe target path outside repo root: $TargetPath"
  }
}

function Format-Bytes {
  param([int64]$Bytes)
  if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
  if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
  if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
  return "$Bytes B"
}

function Measure-PathBytes {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return 0L }
  $item = Get-Item -LiteralPath $Path -Force
  if (-not $item.PSIsContainer) { return [int64]$item.Length }
  $sum = 0L
  Get-ChildItem -LiteralPath $Path -Force -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
    $sum += [int64]$_.Length
  }
  return $sum
}

function Find-DefaultSources {
  param([string]$RootPath)
  $parent = Split-Path -Parent $RootPath
  $leaf = Split-Path -Leaf $RootPath
  $names = @(
    "PsyArch-Agent-main",
    "PsyArch-Agent-old",
    "PsyArch-Agent_old",
    "PsyArch-Agent-backup",
    "PsyArch-Agent_backup",
    "$leaf-main",
    "$leaf-old",
    "$leaf-backup"
  )

  $paths = [System.Collections.Generic.List[string]]::new()
  foreach ($name in $names) {
    $candidate = Join-Path $parent $name
    if ((Test-Path -LiteralPath $candidate) -and (Test-RepoLike $candidate) -and (Test-HasMigratableData $candidate)) {
      $resolved = Resolve-ExistingPath $candidate
      if (-not (Normalize-FullPath $resolved).Equals((Normalize-FullPath $RootPath), [System.StringComparison]::OrdinalIgnoreCase)) {
        $paths.Add($resolved)
      }
    }
  }
  return $paths | Sort-Object -Unique
}

function Choose-Source {
  param([string]$RootPath)
  $candidates = @(Find-DefaultSources $RootPath)
  if ($candidates.Count -eq 1) {
    Write-Host "[PA] Auto-detected old data folder:"
    Write-Host "     $($candidates[0])"
    return $candidates[0]
  }

  Write-Host "[PA] Please choose the old PA folder that contains your previous config/data."
  if ($candidates.Count -gt 1) {
    Write-Host ""
    for ($i = 0; $i -lt $candidates.Count; $i += 1) {
      Write-Host ("  {0}. {1}" -f ($i + 1), $candidates[$i])
    }
    Write-Host ""
    $answer = Read-Host "Input number, or paste a full old folder path"
    $num = 0
    if ([int]::TryParse($answer, [ref]$num) -and $num -ge 1 -and $num -le $candidates.Count) {
      return $candidates[$num - 1]
    }
    return $answer
  }

  Write-Host "Example: E:\PsyArch-Agent-main"
  return (Read-Host "Old PA folder path")
}

function Add-CopyTask {
  param(
    [System.Collections.Generic.List[object]]$Tasks,
    [string]$Rel,
    [string]$Label
  )
  $Tasks.Add([pscustomobject]@{
    Rel = $Rel
    Label = $Label
  })
}

function Copy-TaskItem {
  param(
    [string]$SourceRoot,
    [string]$RootPath,
    [string]$BackupRoot,
    [string]$Rel,
    [string]$Label,
    [switch]$PreviewMode
  )

  $src = Join-Path $SourceRoot $Rel
  if (-not (Test-Path -LiteralPath $src)) {
    return [pscustomobject]@{
      Rel = $Rel
      Label = $Label
      Status = "missing"
      Bytes = 0L
    }
  }

  $dst = Join-Path $RootPath $Rel
  $bytes = Measure-PathBytes $src
  if ($PreviewMode) {
    return [pscustomobject]@{
      Rel = $Rel
      Label = $Label
      Status = "preview"
      Bytes = $bytes
    }
  }

  Assert-UnderRoot $RootPath $dst
  $dstParent = Split-Path -Parent $dst
  if (-not (Test-Path -LiteralPath $dstParent)) {
    New-Item -ItemType Directory -Path $dstParent -Force | Out-Null
  }

  $backedUp = $false
  if (Test-Path -LiteralPath $dst) {
    $backupDst = Join-Path $BackupRoot $Rel
    Assert-UnderRoot $RootPath $backupDst
    $backupParent = Split-Path -Parent $backupDst
    if (-not (Test-Path -LiteralPath $backupParent)) {
      New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
    }
    Copy-Item -LiteralPath $dst -Destination $backupDst -Recurse -Force
    Remove-Item -LiteralPath $dst -Recurse -Force
    $backedUp = $true
  }

  Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
  return [pscustomobject]@{
    Rel = $Rel
    Label = $Label
    Status = $(if ($backedUp) { "copied_with_backup" } else { "copied" })
    Bytes = $bytes
  }
}

$rootPath = Resolve-RepoRoot $Root
if (-not (Test-RepoLike $rootPath)) {
  Write-Host "[ERROR] New root does not look like PsyArch-Agent: $rootPath"
  exit 1
}

if ([string]::IsNullOrWhiteSpace($Source)) {
  $Source = Choose-Source $rootPath
}

if ([string]::IsNullOrWhiteSpace($Source)) {
  Write-Host "[ERROR] No old folder was selected."
  exit 1
}

$sourceRoot = Resolve-ExistingPath $Source
if (-not (Test-RepoLike $sourceRoot)) {
  Write-Host "[ERROR] Source does not look like PsyArch-Agent: $sourceRoot"
  exit 1
}
if (-not (Test-HasMigratableData $sourceRoot)) {
  Write-Host "[ERROR] Source has no migratable runtime data: $sourceRoot"
  exit 1
}

$rootFull = Normalize-FullPath $rootPath
$sourceFull = Normalize-FullPath $sourceRoot
if ($sourceFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -or (Is-UnderRoot $rootPath $sourceRoot)) {
  Write-Host "[ERROR] Source must be an older folder outside the new repo root."
  exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Join-Path $rootPath ("observatory\outputs\migration_backups\before_migration_{0}" -f $timestamp)
$tasks = [System.Collections.Generic.List[object]]::new()

$agentDir = Join-Path $sourceRoot "observatory\outputs\agent"
if (Test-Path -LiteralPath $agentDir) {
  Get-ChildItem -LiteralPath $agentDir -Force -File -ErrorAction SilentlyContinue | ForEach-Object {
    $extension = $_.Extension.ToLowerInvariant()
    $isLogLike = $extension -in @(".jsonl", ".log", ".tmp", ".gz")
    if ((-not $isLogLike) -or $IncludeLogs) {
      Add-CopyTask $tasks ("observatory\outputs\agent\{0}" -f $_.Name) "Agent file"
    }
  }
  Get-ChildItem -LiteralPath $agentDir -Force -Directory -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -notin @("migration_backups", "__pycache__", ".pytest_cache")
  } | ForEach-Object {
    Add-CopyTask $tasks ("observatory\outputs\agent\{0}" -f $_.Name) "Agent data directory"
  }
}

$autoTunerDir = Join-Path $sourceRoot "observatory\outputs\auto_tuner"
if (Test-Path -LiteralPath $autoTunerDir) {
  foreach ($name in @("config.json", "rules.json", "state.json", "rollback_points.json", "llm_config.json")) {
    Add-CopyTask $tasks ("observatory\outputs\auto_tuner\{0}" -f $name) "AP auto-tuner file"
  }
  Add-CopyTask $tasks "observatory\outputs\auto_tuner\overrides" "AP auto-tuner persisted overrides"
}

Add-CopyTask $tasks "hdb\data" "AP/HDB long-term data"

$tasks = @($tasks | Sort-Object Rel -Unique)
if ($tasks.Count -eq 0) {
  Write-Host "[ERROR] No migratable files were found."
  exit 1
}

Write-Host "======================================"
Write-Host "  PsyArch-Agent user data migration"
Write-Host "======================================"
Write-Host "New folder : $rootPath"
Write-Host "Old folder : $sourceRoot"
Write-Host "Backup dir : $backupRoot"
Write-Host "Mode       : $(if ($Preview) { 'preview only' } else { 'copy with backup' })"
Write-Host "Logs       : $(if ($IncludeLogs) { 'included' } else { 'large jsonl/log files skipped by default' })"
Write-Host ""
Write-Host "Please close old PA windows before copying. The old folder will not be deleted."
Write-Host ""

if (-not $Preview) {
  $answer = Read-Host "Type YES to start migration"
  if ($answer -ne "YES") {
    Write-Host "Cancelled."
    exit 0
  }
  New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
}

$results = [System.Collections.Generic.List[object]]::new()
foreach ($task in $tasks) {
  $result = Copy-TaskItem `
    -SourceRoot $sourceRoot `
    -RootPath $rootPath `
    -BackupRoot $backupRoot `
    -Rel $task.Rel `
    -Label $task.Label `
    -PreviewMode:$Preview
  $results.Add($result)
}

$copied = @($results | Where-Object { $_.Status -in @("copied", "copied_with_backup", "preview") })
$missing = @($results | Where-Object { $_.Status -eq "missing" })
$totalBytes = 0L
$copied | ForEach-Object { $totalBytes += [int64]$_.Bytes }

Write-Host ""
Write-Host "Summary"
Write-Host ("  Items ready/copied : {0}" -f $copied.Count)
Write-Host ("  Missing skipped    : {0}" -f $missing.Count)
Write-Host ("  Data size          : {0}" -f (Format-Bytes $totalBytes))
Write-Host ""

$copied | Select-Object -First 80 | ForEach-Object {
  Write-Host ("  [{0}] {1} ({2})" -f $_.Status, $_.Rel, (Format-Bytes ([int64]$_.Bytes)))
}
if ($copied.Count -gt 80) {
  Write-Host ("  ... {0} more item(s)" -f ($copied.Count - 80))
}

if ($Preview) {
  Write-Host ""
  Write-Host "Preview finished. No files were copied."
  exit 0
}

Write-Host ""
Write-Host "Migration finished."
Write-Host "Next:"
Write-Host "  1. Start PA from the NEW folder only."
Write-Host "  2. Open http://127.0.0.1:8765/next/ and press Ctrl+F5 if the page still looks old."
Write-Host "  3. After confirming config/persona/history are correct, you may archive the old folder."
Write-Host "  4. If the old outputs folder was huge, run 清理日志和临时输出.bat in the old folder before keeping it."

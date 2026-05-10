param(
  [string]$Root = "",
  [string]$Package = "",
  [switch]$Preview,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

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
  return (Test-Path -LiteralPath (Join-Path $Path "observatory")) -and
    (Test-Path -LiteralPath (Join-Path $Path "hdb"))
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

function Get-RelativePathCompat {
  param(
    [string]$RootPath,
    [string]$TargetPath
  )
  $rootFull = Normalize-FullPath $RootPath
  $targetFull = [System.IO.Path]::GetFullPath($TargetPath)
  if (-not (Is-UnderRoot $rootFull $targetFull)) {
    throw "target path outside repo root: $TargetPath"
  }
  if ($targetFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    return ""
  }
  return $targetFull.Substring($rootFull.Length).TrimStart(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
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

function Get-MigrationPackageName {
  return ("PA" + [char]0x7528 + [char]0x6237 + [char]0x6570 + [char]0x636E + [char]0x8FC1 + [char]0x79FB + [char]0x5305 + ".zip")
}

function Read-ZipText {
  param([System.IO.Compression.ZipArchiveEntry]$Entry)
  $stream = $Entry.Open()
  try {
    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
    try {
      return $reader.ReadToEnd()
    } finally {
      $reader.Dispose()
    }
  } finally {
    $stream.Dispose()
  }
}

function Backup-ExistingFile {
  param(
    [string]$RootPath,
    [string]$BackupRoot,
    [string]$TargetPath
  )
  if (-not (Test-Path -LiteralPath $TargetPath)) {
    return $false
  }
  Assert-UnderRoot $RootPath $TargetPath
  $rel = Get-RelativePathCompat -RootPath $RootPath -TargetPath $TargetPath
  $backupPath = Join-Path $BackupRoot $rel
  Assert-UnderRoot $RootPath $backupPath
  $backupParent = Split-Path -Parent $backupPath
  if (-not (Test-Path -LiteralPath $backupParent)) {
    New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
  }
  Copy-Item -LiteralPath $TargetPath -Destination $backupPath -Force
  return $true
}

$rootPath = Resolve-RepoRoot $Root
if (-not (Test-RepoLike $rootPath)) {
  Write-Host "[ERROR] Root does not look like PsyArch-Agent: $rootPath"
  exit 1
}

if ([string]::IsNullOrWhiteSpace($Package)) {
  $Package = Join-Path $rootPath (Get-MigrationPackageName)
}

$packagePath = (Resolve-Path -LiteralPath $Package).Path
if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) {
  Write-Host "[ERROR] Package not found: $packagePath"
  exit 1
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$zip = [System.IO.Compression.ZipFile]::OpenRead($packagePath)
try {
  $manifestEntry = $zip.GetEntry("manifest.json")
  if (-not $manifestEntry) {
    Write-Host "[ERROR] Missing manifest.json. This is not a valid PA migration package."
    exit 1
  }
  $manifest = Read-ZipText $manifestEntry | ConvertFrom-Json
  if ($manifest.package_type -ne "psyarch_agent_user_data") {
    Write-Host "[ERROR] Invalid package_type: $($manifest.package_type)"
    exit 1
  }

  $entries = @($zip.Entries | Where-Object {
    $_.FullName -like "payload/*" -and
    -not [string]::IsNullOrWhiteSpace($_.Name)
  })
  if ($entries.Count -eq 0) {
    Write-Host "[ERROR] Package has no payload files."
    exit 1
  }

  $unsafe = @()
  foreach ($entry in $entries) {
    $rel = $entry.FullName.Substring("payload/".Length).Replace("/", "\")
    if ([string]::IsNullOrWhiteSpace($rel) -or [System.IO.Path]::IsPathRooted($rel) -or $rel.Split("\") -contains "..") {
      $unsafe += $entry.FullName
      continue
    }
    $targetPath = Join-Path $rootPath $rel
    if (-not (Is-UnderRoot $rootPath $targetPath)) {
      $unsafe += $entry.FullName
    }
  }
  if ($unsafe.Count -gt 0) {
    Write-Host "[ERROR] Unsafe zip path found:"
    $unsafe | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" }
    exit 1
  }

  $totalBytes = 0L
  foreach ($entry in $entries) {
    $totalBytes += [int64]$entry.Length
  }

  $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $backupRoot = Join-Path $rootPath ("observatory\outputs\migration_backups\before_unpack_{0}" -f $timestamp)

  Write-Host "======================================"
  Write-Host "  PsyArch-Agent user data restore"
  Write-Host "======================================"
  Write-Host "Target folder : $rootPath"
  Write-Host "Package       : $packagePath"
  Write-Host "Source folder : $($manifest.source_root)"
  Write-Host "Files         : $($entries.Count)"
  Write-Host "Data size     : $(Format-Bytes $totalBytes)"
  Write-Host "Backup dir    : $backupRoot"
  Write-Host "Mode          : $(if ($Preview) { 'preview only' } else { 'restore with file backup' })"
  Write-Host ""

  if ($Preview) {
    $entries | Select-Object -First 120 | ForEach-Object {
      Write-Host ("  {0} ({1})" -f $_.FullName, (Format-Bytes ([int64]$_.Length)))
    }
    if ($entries.Count -gt 120) {
      Write-Host ("  ... {0} more file(s)" -f ($entries.Count - 120))
    }
    Write-Host ""
    Write-Host "Preview finished. No files were restored."
    exit 0
  }

  if (-not $Force) {
    Write-Host "Please close PA before restoring data."
    $answer = Read-Host "Type YES to restore this package"
    if ($answer -ne "YES") {
      Write-Host "Cancelled."
      exit 0
    }
  } else {
    Write-Host "Force mode: restore confirmation skipped."
  }

  New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
  $restored = 0
  $backedUp = 0
  foreach ($entry in $entries) {
    $rel = $entry.FullName.Substring("payload/".Length).Replace("/", "\")
    $targetPath = Join-Path $rootPath $rel
    Assert-UnderRoot $rootPath $targetPath
    $parent = Split-Path -Parent $targetPath
    if (-not (Test-Path -LiteralPath $parent)) {
      New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if (Backup-ExistingFile -RootPath $rootPath -BackupRoot $backupRoot -TargetPath $targetPath) {
      $backedUp += 1
    }
    $stream = $entry.Open()
    try {
      $out = [System.IO.File]::Open($targetPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
      try {
        $stream.CopyTo($out)
      } finally {
        $out.Dispose()
      }
    } finally {
      $stream.Dispose()
    }
    $restored += 1
  }

  Write-Host ""
  Write-Host "Restore finished."
  Write-Host "  Restored files : $restored"
  Write-Host "  Backed up files: $backedUp"
  Write-Host ""
Write-Host "Next:"
  Write-Host "  1. Run the restart/update batch file or the quick-start batch file from this folder."
  Write-Host "  2. Open http://127.0.0.1:8765/next/ and press Ctrl+F5 if needed."
} finally {
  $zip.Dispose()
}

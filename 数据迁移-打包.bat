@echo off
setlocal EnableExtensions

cd /d "%~dp0" || goto :err_cd

set "PA_SELF=%~f0"
set "PA_TEMP_PS=%TEMP%\pa_helper_%RANDOM%%RANDOM%.ps1"
set "PS_CMD="
where powershell >nul 2>nul
if not errorlevel 1 (
  set "PS_CMD=powershell"
) else (
  where pwsh >nul 2>nul
  if not errorlevel 1 (
    set "PS_CMD=pwsh"
  )
)

if "%PS_CMD%"=="" (
  echo [PA] PowerShell not found.
  echo.
  pause
  exit /b 1
)

echo ======================================
echo   PsyArch-Agent data migration pack
echo ======================================
echo Folder: %cd%
echo.
echo This creates a fixed migration zip in this folder.

echo Copy that zip to the new PA folder, then run the restore batch.
echo.

%PS_CMD% -NoProfile -ExecutionPolicy Bypass -Command "$marker='###'+'__PA_PS_PAYLOAD__'+'###'; $raw=[System.IO.File]::ReadAllText($env:PA_SELF, [System.Text.Encoding]::Default); $idx=$raw.IndexOf($marker); if($idx -lt 0){throw 'payload marker missing'}; $payload=$raw.Substring($idx + $marker.Length).TrimStart([char]13,[char]10); [System.IO.File]::WriteAllText($env:PA_TEMP_PS, $payload, [System.Text.UTF8Encoding]::new($false))"
if errorlevel 1 (
  echo [PA] Failed to extract embedded helper.
  echo.
  pause
  exit /b 1
)

%PS_CMD% -NoProfile -ExecutionPolicy Bypass -File "%PA_TEMP_PS%" -Root "%cd%" %*
set "CODE=%ERRORLEVEL%"

if exist "%PA_TEMP_PS%" del /f /q "%PA_TEMP_PS%" >nul 2>nul

echo.
if not "%CODE%"=="0" (
  echo [PA] Pack helper exited with errorlevel=%CODE%.
) else (
  echo [PA] Pack helper finished.
)
echo.
pause
exit /b %CODE%

:err_cd
echo [PA] Failed to cd to script directory.
echo.
pause
exit /b 1

###__PA_PS_PAYLOAD__###param(
  [string]$Root = "",
  [string]$Output = "",
  [switch]$IncludeLogs
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

function Add-FileToZip {
  param(
    [System.IO.Compression.ZipArchive]$Zip,
    [string]$RootPath,
    [string]$FullName,
    [string]$EntryPrefix
  )
  if (-not (Is-UnderRoot $RootPath $FullName)) {
    throw "unsafe source path outside repo root: $FullName"
  }
  $relative = (Get-RelativePathCompat -RootPath $RootPath -TargetPath $FullName).Replace("\", "/")
  $entryName = "$EntryPrefix/$relative"
  [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
    $Zip,
    $FullName,
    $entryName,
    [System.IO.Compression.CompressionLevel]::Optimal
  ) | Out-Null
}

function Add-JsonEntry {
  param(
    [System.IO.Compression.ZipArchive]$Zip,
    [string]$EntryName,
    [object]$Payload
  )
  $entry = $Zip.CreateEntry($EntryName, [System.IO.Compression.CompressionLevel]::Optimal)
  $stream = $entry.Open()
  try {
    $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false))
    try {
      $writer.Write(($Payload | ConvertTo-Json -Depth 8))
    } finally {
      $writer.Dispose()
    }
  } finally {
    $stream.Dispose()
  }
}

function Get-MigratableFiles {
  param(
    [string]$RootPath,
    [switch]$WithLogs
  )
  $files = [System.Collections.Generic.List[System.IO.FileInfo]]::new()

  $agentDir = Join-Path $RootPath "observatory\outputs\agent"
  if (Test-Path -LiteralPath $agentDir) {
    Get-ChildItem -LiteralPath $agentDir -Force -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
      $rel = (Get-RelativePathCompat -RootPath $RootPath -TargetPath $_.FullName).Replace("\", "/")
      if ($rel -match "/migration_backups/") { return $false }
      $ext = $_.Extension.ToLowerInvariant()
      $isLogLike = $ext -in @(".jsonl", ".log", ".tmp", ".gz")
      return $WithLogs -or (-not $isLogLike)
    } | ForEach-Object { $files.Add($_) }
  }

  $autoTunerDir = Join-Path $RootPath "observatory\outputs\auto_tuner"
  if (Test-Path -LiteralPath $autoTunerDir) {
    Get-ChildItem -LiteralPath $autoTunerDir -Force -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
      $rel = (Get-RelativePathCompat -RootPath $RootPath -TargetPath $_.FullName).Replace("\", "/")
      if ($rel -match "/llm_suggestions/") { return $false }
      $ext = $_.Extension.ToLowerInvariant()
      $isLogLike = $ext -in @(".jsonl", ".log", ".tmp", ".gz")
      return $WithLogs -or (-not $isLogLike)
    } | ForEach-Object { $files.Add($_) }
  }

  $hdbData = Join-Path $RootPath "hdb\data"
  if (Test-Path -LiteralPath $hdbData) {
    Get-ChildItem -LiteralPath $hdbData -Force -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
      $ext = $_.Extension.ToLowerInvariant()
      $isLogLike = $ext -in @(".log", ".tmp", ".jsonl", ".gz")
      return $WithLogs -or (-not $isLogLike)
    } | ForEach-Object { $files.Add($_) }
  }

  return @($files | Sort-Object FullName -Unique)
}

$rootPath = Resolve-RepoRoot $Root
if (-not (Test-RepoLike $rootPath)) {
  Write-Host "[ERROR] Root does not look like PsyArch-Agent: $rootPath"
  exit 1
}

if ([string]::IsNullOrWhiteSpace($Output)) {
  $Output = Join-Path $rootPath (Get-MigrationPackageName)
}
$outputPath = [System.IO.Path]::GetFullPath($Output)

if (-not (Is-UnderRoot $rootPath $outputPath)) {
  Write-Host "[ERROR] Output zip must be inside the current PA folder: $outputPath"
  exit 1
}

$files = @(Get-MigratableFiles -RootPath $rootPath -WithLogs:$IncludeLogs)
if ($files.Count -eq 0) {
  Write-Host "[ERROR] No migratable data was found."
  exit 1
}

$totalBytes = 0L
foreach ($file in $files) {
  $totalBytes += [int64]$file.Length
}

if (Test-Path -LiteralPath $outputPath) {
  Remove-Item -LiteralPath $outputPath -Force
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$metadata = [ordered]@{
  package_type = "psyarch_agent_user_data"
  version = 1
  created_at = (Get-Date).ToString("o")
  source_root = $rootPath
  include_logs = [bool]$IncludeLogs
  file_count = $files.Count
  byte_count = $totalBytes
  entry_prefix = "payload"
  note = "Restore with the migration restore batch file from the target PsyArch-Agent folder."
}

$zip = [System.IO.Compression.ZipFile]::Open($outputPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
  Add-JsonEntry -Zip $zip -EntryName "manifest.json" -Payload $metadata
  foreach ($file in $files) {
    Add-FileToZip -Zip $zip -RootPath $rootPath -FullName $file.FullName -EntryPrefix "payload"
  }
} finally {
  $zip.Dispose()
}

$zipInfo = Get-Item -LiteralPath $outputPath -Force
Write-Host "======================================"
Write-Host "  PsyArch-Agent user data package"
Write-Host "======================================"
Write-Host "Root       : $rootPath"
Write-Host "Package    : $outputPath"
Write-Host "Files      : $($files.Count)"
Write-Host "Data size  : $(Format-Bytes $totalBytes)"
Write-Host "Zip size   : $(Format-Bytes ([int64]$zipInfo.Length))"
Write-Host "Logs       : $(if ($IncludeLogs) { 'included' } else { 'skipped by default' })"
Write-Host ""
Write-Host "Next:"
Write-Host ("  1. Copy {0} to the new PsyArch-Agent folder." -f (Get-MigrationPackageName))
Write-Host "  2. Run the migration restore batch file in the new folder."

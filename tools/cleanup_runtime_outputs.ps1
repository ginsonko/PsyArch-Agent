param(
  [string]$Root = "",
  [string]$KeepDays = "1",
  [int64]$LargeCycleBytes = 2097152,
  [int64]$LargeJsonlBytes = 2097152,
  [switch]$Preview
)

$ErrorActionPreference = "Stop"

function Resolve-Root {
  param([string]$Path)
  if ([string]::IsNullOrWhiteSpace($Path)) {
    return (Resolve-Path ".").Path
  }
  return (Resolve-Path -LiteralPath $Path).Path
}

function Is-UnderRoot {
  param(
    [string]$RootPath,
    [string]$TargetPath
  )
  $rootFull = [System.IO.Path]::GetFullPath($RootPath).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
  $targetFull = [System.IO.Path]::GetFullPath($TargetPath).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
  return $targetFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -or
    $targetFull.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase) -or
    $targetFull.StartsWith($rootFull + [System.IO.Path]::AltDirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
}

function Add-DirectoryChildren {
  param(
    [System.Collections.Generic.List[object]]$List,
    [string]$Path,
    [datetime]$Cutoff
  )
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.LastWriteTime -lt $Cutoff) {
      $List.Add($_)
    }
  }
}

function Add-DirectoryByPattern {
  param(
    [System.Collections.Generic.List[object]]$List,
    [string]$Path,
    [string]$Pattern,
    [datetime]$Cutoff
  )
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-ChildItem -LiteralPath $Path -Force -Directory -Filter $Pattern -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.LastWriteTime -lt $Cutoff) {
      $List.Add($_)
    }
  }
}

function Add-FileByPattern {
  param(
    [System.Collections.Generic.List[object]]$List,
    [string]$Path,
    [string]$Pattern,
    [datetime]$Cutoff
  )
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-ChildItem -LiteralPath $Path -Force -File -Filter $Pattern -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.LastWriteTime -lt $Cutoff) {
      $List.Add($_)
    }
  }
}

function Add-LargeFileByPattern {
  param(
    [System.Collections.Generic.List[object]]$List,
    [string]$Path,
    [string]$Pattern,
    [int64]$MinBytes
  )
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-ChildItem -LiteralPath $Path -Force -File -Filter $Pattern -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Length -ge $MinBytes) {
      $List.Add($_)
    }
  }
}

function Add-RecursiveLargeFileByPattern {
  param(
    [System.Collections.Generic.List[object]]$List,
    [string]$Path,
    [string]$Pattern,
    [int64]$MinBytes
  )
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-ChildItem -LiteralPath $Path -Force -Recurse -File -Filter $Pattern -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Length -ge $MinBytes) {
      $List.Add($_)
    }
  }
}

function Add-RecursiveFileByPattern {
  param(
    [System.Collections.Generic.List[object]]$List,
    [string]$Path,
    [string]$Pattern,
    [datetime]$Cutoff
  )
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-ChildItem -LiteralPath $Path -Force -Recurse -File -Filter $Pattern -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.LastWriteTime -lt $Cutoff) {
      $List.Add($_)
    }
  }
}

function Add-ExactDirectory {
  param(
    [System.Collections.Generic.List[object]]$List,
    [string]$Path,
    [datetime]$Cutoff
  )
  if (-not (Test-Path -LiteralPath $Path)) { return }
  $item = Get-Item -LiteralPath $Path -Force
  if ($item.LastWriteTime -lt $Cutoff) {
    $List.Add($item)
  }
}

$rootPath = Resolve-Root $Root

if (-not (Test-Path -LiteralPath (Join-Path $rootPath "observatory"))) {
  Write-Host "[ERROR] Root does not look like the AP prototype repo: $rootPath"
  exit 1
}

$daysNumber = 1.0
if (-not [double]::TryParse([string]$KeepDays, [ref]$daysNumber)) {
  Write-Host "[ERROR] KeepDays must be a number."
  exit 1
}
if ($daysNumber -lt 0) {
  Write-Host "[ERROR] KeepDays must be >= 0."
  exit 1
}

$cutoff = if ($Preview) { [datetime]::MaxValue } elseif ($daysNumber -eq 0) { [datetime]::MaxValue } else { (Get-Date).AddDays(-$daysNumber) }
$targets = [System.Collections.Generic.List[object]]::new()

Add-DirectoryByPattern $targets $rootPath "_tmp_*" $cutoff
Add-DirectoryByPattern $targets $rootPath "bench_logs_*" $cutoff
Add-ExactDirectory $targets (Join-Path $rootPath ".pytest_cache") $cutoff
Add-ExactDirectory $targets (Join-Path $rootPath ".mypy_cache") $cutoff
Add-ExactDirectory $targets (Join-Path $rootPath ".ruff_cache") $cutoff
Add-ExactDirectory $targets (Join-Path $rootPath "reports") $cutoff

Add-FileByPattern $targets $rootPath "_tmp_*.py" $cutoff
Add-FileByPattern $targets $rootPath "_tmp_*.prof" $cutoff
Add-FileByPattern $targets $rootPath "*.log" $cutoff
Add-FileByPattern $targets $rootPath "*.prof" $cutoff

$outputsPath = Join-Path $rootPath "observatory\outputs"
Add-DirectoryChildren $targets (Join-Path $outputsPath "hdb_bench") $cutoff
Add-DirectoryChildren $targets (Join-Path $outputsPath "service_logs") $cutoff
Add-DirectoryChildren $targets (Join-Path $outputsPath "stage2_dataset_probes") $cutoff
Add-DirectoryChildren $targets (Join-Path $outputsPath "stage2_probes") $cutoff
Add-DirectoryChildren $targets (Join-Path $outputsPath "diagnostic_ev_trace_20260427") $cutoff

Add-FileByPattern $targets $outputsPath "cycle_*.json" $cutoff
Add-FileByPattern $targets $outputsPath "cycle_*.html" $cutoff
Add-LargeFileByPattern $targets $outputsPath "cycle_*.json" $LargeCycleBytes
Add-LargeFileByPattern $targets $outputsPath "cycle_*.html" ($LargeCycleBytes * 2)
Add-RecursiveLargeFileByPattern $targets $outputsPath "*.jsonl" $LargeJsonlBytes
Add-RecursiveFileByPattern $targets $outputsPath "*.jsonl.gz" $cutoff
Add-FileByPattern $targets $outputsPath "*.log" $cutoff
Add-FileByPattern $targets $outputsPath "*.tmp" $cutoff
Add-FileByPattern $targets $outputsPath "dataset_diagnostics_*.json" $cutoff
Add-FileByPattern $targets $outputsPath "*_diagnostics_*.json" $cutoff
Add-FileByPattern $targets $outputsPath "*_report_*.md" $cutoff
Add-FileByPattern $targets $outputsPath "state_pool_*_report_*.md" $cutoff
Add-FileByPattern $targets $outputsPath "tmp_*.py" $cutoff

$unique = $targets |
  Where-Object { $_ -ne $null } |
  Sort-Object FullName -Unique |
  Where-Object { Is-UnderRoot $rootPath $_.FullName }

$totalBytes = 0L
$fileCount = 0
$dirCount = 0
foreach ($item in $unique) {
  if ($item.PSIsContainer) {
    $dirCount += 1
  } else {
    $fileCount += 1
    $totalBytes += [int64]$item.Length
  }
}

Write-Host "Root: $rootPath"
if ($Preview) {
  Write-Host "Mode: preview only"
} elseif ($daysNumber -eq 0) {
  Write-Host "Mode: delete all cleanup targets"
} else {
  Write-Host ("Mode: keep last {0} day(s)" -f $daysNumber)
  Write-Host ("Cutoff: {0}" -f $cutoff.ToString("yyyy-MM-dd HH:mm:ss"))
}
Write-Host ("Targets: {0}" -f $unique.Count)
Write-Host ("Target dirs: {0}" -f $dirCount)
Write-Host ("Target files: {0}" -f $fileCount)
Write-Host ("Direct file bytes: {0}" -f $totalBytes)
Write-Host "Directory sizes are not recursively counted, to keep preview fast."
Write-Host "Preserved: config files, HDB data, latest.json/latest.html, stickers, generated images, and incoming attachments."
Write-Host ""

$unique | Select-Object -First 120 | ForEach-Object {
  $kind = if ($_.PSIsContainer) { "DIR " } elseif ($_.Extension -eq ".jsonl" -and $_.Length -ge $LargeJsonlBytes) { "TRIM" } else { "FILE" }
  Write-Host ("[{0}] {1}" -f $kind, $_.FullName)
}
if ($unique.Count -gt 120) {
  Write-Host ("... {0} more target(s)" -f ($unique.Count - 120))
}

if ($Preview) {
  Write-Host ""
  Write-Host "Preview finished. No files were deleted."
  exit 0
}

if ($unique.Count -eq 0) {
  Write-Host ""
  Write-Host "Nothing to delete."
  exit 0
}

Write-Host ""
$confirm = Read-Host "Type YES to delete these targets"
if ($confirm -ne "YES") {
  Write-Host "Cancelled."
  exit 0
}

$deleted = 0
$trimmed = 0
$failed = 0
foreach ($item in $unique) {
  try {
    if ((-not $item.PSIsContainer) -and $item.Extension -eq ".jsonl" -and $item.Length -ge $LargeJsonlBytes) {
      $archive = Join-Path $item.DirectoryName ("{0}.{1}.jsonl.gz" -f $item.BaseName, (Get-Date -Format "yyyyMMdd-HHmmss"))
      $inputStream = [System.IO.File]::OpenRead($item.FullName)
      try {
        $outputStream = [System.IO.File]::Create($archive)
        try {
          $gzipStream = [System.IO.Compression.GzipStream]::new($outputStream, [System.IO.Compression.CompressionLevel]::Optimal)
          try {
            $inputStream.CopyTo($gzipStream)
          } finally {
            $gzipStream.Dispose()
          }
        } finally {
          $outputStream.Dispose()
        }
      } finally {
        $inputStream.Dispose()
      }
      Set-Content -LiteralPath $item.FullName -Value "" -Encoding UTF8
      $trimmed += 1
    } else {
      Remove-Item -LiteralPath $item.FullName -Force -Recurse -ErrorAction Stop
      $deleted += 1
    }
  } catch {
    $failed += 1
    Write-Host ("[WARN] Failed: {0} :: {1}" -f $item.FullName, $_.Exception.Message)
  }
}

Write-Host ""
Write-Host ("Deleted: {0}" -f $deleted)
Write-Host ("Trimmed JSONL: {0}" -f $trimmed)
Write-Host ("Failed: {0}" -f $failed)
if ($failed -gt 0) {
  exit 1
}
exit 0

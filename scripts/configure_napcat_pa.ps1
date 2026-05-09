param(
    [string] $NapCatDir = "",
    [string] $WebhookUrl = "http://127.0.0.1:8765/api/agent/napcat/event",
    [string] $HttpHost = "127.0.0.1",
    [int] $HttpPort = 3000,
    [int] $WebSocketPort = 3001,
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

function Read-JsonObject {
    param([string] $Path)
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        if (-not [string]::IsNullOrWhiteSpace($raw)) {
            return ($raw | ConvertFrom-Json)
        }
    }
    return ([pscustomobject]@{ network = [pscustomobject]@{} })
}

function Ensure-ArrayProperty {
    param(
        [object] $Object,
        [string] $Name
    )
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop -or $null -eq $prop.Value) {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue @() -Force
        return
    }
    if ($prop.Value -isnot [System.Collections.IEnumerable] -or $prop.Value -is [string]) {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue @() -Force
    }
}

function Set-ObjectProperty {
    param(
        [object] $Object,
        [string] $Name,
        [object] $Value
    )
    $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
}

function Find-ByName {
    param(
        [object[]] $Items,
        [string] $Name
    )
    foreach ($item in $Items) {
        if ($null -ne $item -and $item.PSObject.Properties["name"] -and [string]::Equals([string]$item.name, $Name, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $item
        }
    }
    return $null
}

function Patch-OneBotConfig {
    param([object] $Config)

    if ($null -eq $Config.PSObject.Properties["network"] -or $null -eq $Config.network) {
        Set-ObjectProperty $Config "network" ([pscustomobject]@{})
    }
    $network = $Config.network
    foreach ($name in @("httpServers", "httpSseServers", "httpClients", "websocketServers", "websocketClients", "plugins")) {
        Ensure-ArrayProperty $network $name
    }

    $httpServers = @($network.httpServers)
    $httpServer = Find-ByName $httpServers "HTTP"
    if ($null -eq $httpServer) {
        $httpServer = [pscustomobject]@{}
        $httpServers += $httpServer
        Set-ObjectProperty $network "httpServers" $httpServers
    }
    Set-ObjectProperty $httpServer "enable" $true
    Set-ObjectProperty $httpServer "name" "HTTP"
    Set-ObjectProperty $httpServer "host" $HttpHost
    Set-ObjectProperty $httpServer "port" $HttpPort
    Set-ObjectProperty $httpServer "enableCors" $true
    if ($null -eq $httpServer.PSObject.Properties["enableWebsocket"]) { Set-ObjectProperty $httpServer "enableWebsocket" $false }
    Set-ObjectProperty $httpServer "messagePostFormat" "array"
    if ($null -eq $httpServer.PSObject.Properties["token"]) { Set-ObjectProperty $httpServer "token" "" }
    if ($null -eq $httpServer.PSObject.Properties["debug"]) { Set-ObjectProperty $httpServer "debug" $false }

    $httpClients = @($network.httpClients)
    $client = Find-ByName $httpClients "PA Agent Webhook"
    if ($null -eq $client) {
        $client = [pscustomobject]@{}
        $httpClients += $client
        Set-ObjectProperty $network "httpClients" $httpClients
    }
    Set-ObjectProperty $client "enable" $true
    Set-ObjectProperty $client "name" "PA Agent Webhook"
    Set-ObjectProperty $client "url" $WebhookUrl
    Set-ObjectProperty $client "messagePostFormat" "array"
    Set-ObjectProperty $client "reportSelfMessage" $false
    if ($null -eq $client.PSObject.Properties["token"]) { Set-ObjectProperty $client "token" "" }
    if ($null -eq $client.PSObject.Properties["debug"]) { Set-ObjectProperty $client "debug" $false }

    $websocketServers = @($network.websocketServers)
    $websocketServer = Find-ByName $websocketServers "WebSocket"
    if ($null -eq $websocketServer) {
        $websocketServer = [pscustomobject]@{}
        $websocketServers += $websocketServer
        Set-ObjectProperty $network "websocketServers" $websocketServers
    }
    Set-ObjectProperty $websocketServer "enable" $true
    Set-ObjectProperty $websocketServer "name" "WebSocket"
    Set-ObjectProperty $websocketServer "host" $HttpHost
    Set-ObjectProperty $websocketServer "port" $WebSocketPort
    Set-ObjectProperty $websocketServer "reportSelfMessage" $false
    Set-ObjectProperty $websocketServer "enableForcePushEvent" $true
    Set-ObjectProperty $websocketServer "messagePostFormat" "array"
    if ($null -eq $websocketServer.PSObject.Properties["token"]) { Set-ObjectProperty $websocketServer "token" "" }
    if ($null -eq $websocketServer.PSObject.Properties["debug"]) { Set-ObjectProperty $websocketServer "debug" $false }
    if ($null -eq $websocketServer.PSObject.Properties["heartInterval"]) { Set-ObjectProperty $websocketServer "heartInterval" 30000 }

    if ($null -eq $Config.PSObject.Properties["musicSignUrl"]) { Set-ObjectProperty $Config "musicSignUrl" "" }
    if ($null -eq $Config.PSObject.Properties["enableLocalFile2Url"]) { Set-ObjectProperty $Config "enableLocalFile2Url" $false }
    if ($null -eq $Config.PSObject.Properties["parseMultMsg"]) { Set-ObjectProperty $Config "parseMultMsg" $false }
    if ($null -eq $Config.PSObject.Properties["imageDownloadProxy"]) { Set-ObjectProperty $Config "imageDownloadProxy" "" }
    return $Config
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($NapCatDir)) {
    $NapCatDir = Join-Path (Split-Path -Parent $repoRoot) "NapCatQQ"
}
$napcatPath = Resolve-AbsolutePath $NapCatDir

Write-PA "NapCat directory: $napcatPath"
Write-PA "Webhook URL: $WebhookUrl"
if ($DryRun) {
    Write-PA "Dry-run enabled. No files will be changed."
}

if (-not (Test-Path -LiteralPath $napcatPath -PathType Container)) {
    throw "NapCat directory was not found. Run 一键拉取或更新NapCat.bat first, or pass -NapCatDir."
}

$candidateRelativePaths = @(
    "packages\napcat-develop\config\onebot11.json",
    "packages\napcat-develop\dist\config\onebot11.json",
    "packages\napcat-shell\dist\config\onebot11.json",
    "packages\napcat-shell-loader\config\onebot11.json"
)

$sourcePath = Join-Path $napcatPath "packages\napcat-develop\config\onebot11.json"
$sourceConfig = Read-JsonObject $sourcePath
$patched = Patch-OneBotConfig $sourceConfig
$json = $patched | ConvertTo-Json -Depth 80

$written = @()
foreach ($relative in $candidateRelativePaths) {
    $path = Join-Path $napcatPath $relative
    $parent = Split-Path -Parent $path
    if ($relative -ne "packages\napcat-develop\config\onebot11.json" -and -not (Test-Path -LiteralPath $parent -PathType Container)) {
        Write-PA "Skip missing dist directory: $parent"
        continue
    }
    if ($DryRun) {
        Write-PA "Would write: $path"
    } else {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $backup = "$path.pa-agent.bak"
            if (-not (Test-Path -LiteralPath $backup -PathType Leaf)) {
                Copy-Item -LiteralPath $path -Destination $backup -Force
                Write-PA "Backup created: $backup"
            }
        }
        Set-Content -LiteralPath $path -Value $json -Encoding UTF8
        $written += $path
        Write-PA "Configured: $path"
    }
}

if ($DryRun) {
    Write-PA "Dry-run complete."
} else {
    Write-PA "Configured files: $($written.Count)"
    Write-PA "NapCat WebUI should show HTTP server 127.0.0.1:$HttpPort and HTTP client PA Agent Webhook."
}

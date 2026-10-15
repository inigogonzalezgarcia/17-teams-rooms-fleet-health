<#
.SYNOPSIS
    Exports Teams Rooms devices and their health from Microsoft Graph into one JSON file
    that rooms_health can read.

.DESCRIPTION
    Calls GET /teamwork/devices and, for each device, GET /teamwork/devices/{id}/health,
    then writes { "value": [ device + health, ... ] }.

    The teamwork device APIs are in the Microsoft Graph beta endpoint, so field names can change.
    The Python side reads them defensively (missing sections become "unknown").

    Read-only. Sign in with your own admin account; the only scope requested is TeamworkDevice.Read.All.

.EXAMPLE
    .\Export-TeamsRoomsHealth.ps1 -OutputPath .\teams_rooms_health.json
    .\Export-TeamsRoomsHealth.ps1 -DeviceType teamsRoom,collaborationBar
#>
[CmdletBinding()]
param(
    [string]$OutputPath = ".\teams_rooms_health.json",
    [string[]]$DeviceType = @("teamsRoom", "collaborationBar", "surfaceHub")
)

$ErrorActionPreference = "Stop"

if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Authentication)) {
    throw "Install the Microsoft Graph PowerShell SDK first: Install-Module Microsoft.Graph.Authentication -Scope CurrentUser"
}

Connect-MgGraph -Scopes "TeamworkDevice.Read.All" -NoWelcome

$base = "https://graph.microsoft.com/beta/teamwork/devices"
$devices = @()
$uri = $base
while ($uri) {
    $page = Invoke-MgGraphRequest -Method GET -Uri $uri
    $devices += $page.value
    $uri = $page.'@odata.nextLink'
}

$devices = $devices | Where-Object { $DeviceType -contains $_.deviceType }
Write-Host "Found $($devices.Count) devices of type $($DeviceType -join ', ')"

$out = foreach ($d in $devices) {
    try {
        $health = Invoke-MgGraphRequest -Method GET -Uri "$base/$($d.id)/health"
    }
    catch {
        Write-Warning "No health for $($d.id): $($_.Exception.Message)"
        $health = $null
    }
    $d["health"] = $health
    $d
}

@{ value = @($out) } | ConvertTo-Json -Depth 12 | Set-Content -Path $OutputPath -Encoding UTF8
Write-Host "Saved $OutputPath. It contains room account names and serial numbers: keep it inside your organisation."

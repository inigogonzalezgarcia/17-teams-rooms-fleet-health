<#
.SYNOPSIS
    Optional. Exports today's bookings (start and end only) for the rooms in rooms.csv,
    so the morning check can put rooms with an early meeting first.

.DESCRIPTION
    Reads /users/{room}/calendarView for each room account and writes room_account,start,end in UTC.
    Subjects, organisers and attendees are NOT requested ($select=start,end).

    Needs Calendars.Read. In production, use an app registration with application permission and
    restrict it to the room mailboxes (Exchange Online RBAC for Applications or an application access
    policy), instead of giving it access to every mailbox.

.EXAMPLE
    .\Export-RoomBookings.ps1 -RoomsCsv .\rooms.csv -OutputPath .\bookings.csv
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$RoomsCsv,
    [string]$OutputPath = ".\bookings.csv",
    [datetime]$Day = (Get-Date).Date
)

$ErrorActionPreference = "Stop"
Connect-MgGraph -Scopes "Calendars.Read" -NoWelcome

$start = $Day.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$end = $Day.AddDays(1).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$headers = @{ Prefer = 'outlook.timezone="UTC"' }

$rows = foreach ($room in Import-Csv $RoomsCsv) {
    $uri = "https://graph.microsoft.com/v1.0/users/$($room.room_account)/calendarView" +
           "?startDateTime=$start&endDateTime=$end&`$select=start,end&`$top=100"
    try {
        $events = (Invoke-MgGraphRequest -Method GET -Uri $uri -Headers $headers).value
    }
    catch {
        Write-Warning "$($room.room_account): $($_.Exception.Message)"
        continue
    }
    foreach ($ev in $events) {
        [pscustomobject]@{
            room_account = $room.room_account
            start        = "$($ev.start.dateTime.Substring(0,19))Z"
            end          = "$($ev.end.dateTime.Substring(0,19))Z"
        }
    }
}

$rows | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding UTF8
Write-Host "Saved $($rows.Count) bookings to $OutputPath"

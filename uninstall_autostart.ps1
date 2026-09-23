#Requires -Version 5.1

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$taskName = "Feishu PC Controller"
$shortcutPath = Join-Path (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup") "Feishu PC Controller.lnk"

try {
    $removed = $false
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        $removed = $true
        Write-Host "Autostart task removed: $taskName"
    }

    if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
        Remove-Item -LiteralPath $shortcutPath -Force
        $removed = $true
        Write-Host "Startup shortcut removed: $shortcutPath"
    }

    if (-not $removed) {
        Write-Host "Autostart is not installed: $taskName"
    }
}
catch {
    Write-Error $_
    exit 1
}

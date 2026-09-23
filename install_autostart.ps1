#Requires -Version 5.1

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$taskName = "Feishu PC Controller"
$projectRoot = (Get-Item -LiteralPath $PSScriptRoot).FullName
$launcher = Join-Path -Path $projectRoot -ChildPath "start_feishu_stack.bat"
$envFile = Join-Path -Path $projectRoot -ChildPath ".env"
$runtimeDirectory = Join-Path -Path $projectRoot -ChildPath "runtime"
$pythonPathFile = Join-Path -Path $runtimeDirectory -ChildPath "python-path.txt"
$startupDirectory = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$shortcutPath = Join-Path $startupDirectory "Feishu PC Controller.lnk"

try {
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw "Missing .env file: $envFile"
    }

    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        throw "Missing launcher: $launcher"
    }

    $pythonCommand = Get-Command python -ErrorAction Stop
    $pythonPath = $pythonCommand.Source
    if (-not [IO.Path]::IsPathRooted($pythonPath) -or -not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Could not resolve an absolute python.exe path from the current environment"
    }
    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
    Set-Content -LiteralPath $pythonPathFile -Value $pythonPath -Encoding ascii

    $actionArguments = '/d /c ""{0}""' -f $launcher
    $action = New-ScheduledTaskAction `
        -Execute $env:ComSpec `
        -Argument $actionArguments `
        -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal `
        -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -Hidden `
        -StartWhenAvailable `
        -RestartCount 5 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)

    try {
        Register-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
            -Force | Out-Null

        Start-ScheduledTask -TaskName $taskName
        Write-Host "Autostart installed and task started: $taskName"
    }
    catch {
        if ($_.Exception.Message -notmatch "Access is denied|拒绝访问") {
            throw
        }

        New-Item -ItemType Directory -Path $startupDirectory -Force | Out-Null
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $env:ComSpec
        $shortcut.Arguments = $actionArguments
        $shortcut.WorkingDirectory = $projectRoot
        $shortcut.WindowStyle = 7
        $shortcut.Description = "Start Feishu PC Controller"
        $shortcut.Save()
        Write-Host "Task Scheduler access was denied; autostart installed in the current user's Startup folder."
        Write-Host "Shortcut: $shortcutPath"
    }
}
catch {
    Write-Error $_
    exit 1
}

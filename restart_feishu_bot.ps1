#Requires -Version 5.1

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$controllerRoot = (Get-Item -LiteralPath $PSScriptRoot).FullName
$port = 8760
$envFile = Join-Path $controllerRoot ".env"

if (Test-Path -LiteralPath $envFile -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*FEISHU_CONTROLLER_PORT\s*=\s*(.*?)\s*$') {
            $portValue = $Matches[1].Trim().Trim('"').Trim("'")
            $parsedPort = 0
            if (-not [int]::TryParse($portValue, [ref]$parsedPort) -or
                $parsedPort -lt 1 -or $parsedPort -gt 65535) {
                throw "FEISHU_CONTROLLER_PORT must be an integer between 1 and 65535."
            }
            $port = $parsedPort
            break
        }
    }
}

$listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    $expectedScript = [IO.Path]::GetFullPath((Join-Path $controllerRoot "run_feishu_bot.py"))
    $processIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    $processes = @()

    foreach ($processId in $processIds) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
        if ($null -eq $process) {
            throw "Could not verify process $processId listening on port $port; refusing to stop it."
        }

        $processName = [IO.Path]::GetFileName([string]$process.ExecutablePath)
        $commandLine = [string]$process.CommandLine
        if ($processName -notin @("python.exe", "pythonw.exe") -or
            $commandLine.IndexOf($expectedScript, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw "Port $port is owned by another process (PID $processId); refusing to stop it."
        }
        $processes += $process
    }

    foreach ($process in $processes) {
        Write-Host "[controller] stopping verified process PID $($process.ProcessId)"
        Stop-Process -Id $process.ProcessId -ErrorAction Stop
    }

    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 250
        $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        if ($listeners.Count -eq 0) {
            break
        }
    } while ((Get-Date) -lt $deadline)

    if ($listeners.Count -gt 0) {
        throw "Port $port is still listening after stopping the controller; refusing to start another instance."
    }
} else {
    Write-Host "[controller] port $port is not listening; starting the controller."
}

$launcher = Join-Path $controllerRoot "start_feishu_bot.bat"
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Controller launcher not found: $launcher"
}

& $launcher
if ($LASTEXITCODE -ne 0) {
    throw "Controller launcher failed with exit code $LASTEXITCODE."
}

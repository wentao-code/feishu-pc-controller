#Requires -Version 5.1

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$controllerRoot = (Get-Item -LiteralPath $PSScriptRoot).FullName
$envFile = Join-Path $controllerRoot ".env"

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Missing .env file: $envFile"
}

foreach ($line in Get-Content -LiteralPath $envFile) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or $trimmed -notmatch '^([^=]+)=(.*)$') {
        continue
    }
    $name = $Matches[1].Trim()
    $value = $Matches[2].Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
        ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
}

$env:PYTHONPATH = if ($env:PYTHONPATH) {
    "$controllerRoot;$($env:PYTHONPATH)"
} else {
    $controllerRoot
}

$pythonPathFile = Join-Path $controllerRoot "runtime\python-path.txt"
$python = $null
if (Test-Path -LiteralPath $pythonPathFile -PathType Leaf) {
    $candidate = (Get-Content -LiteralPath $pythonPathFile -Raw).Trim()
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        $python = $candidate
    }
}
if (-not $python) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $command -and $command.Source) {
        $python = $command.Source
    }
}
if (-not $python) {
    throw "Could not resolve python.exe. Run install_autostart.ps1 or add Python to PATH."
}

$controllerPort = if ($env:FEISHU_CONTROLLER_PORT) {
    [int]$env:FEISHU_CONTROLLER_PORT
} else {
    8760
}
$client = [Net.Sockets.TcpClient]::new()
try {
    $connect = $client.BeginConnect("127.0.0.1", $controllerPort, $null, $null)
    if ($connect.AsyncWaitHandle.WaitOne(500)) {
        try {
            $client.EndConnect($connect)
            Write-Host "[controller] already listening on 127.0.0.1:$controllerPort; skipped"
            Write-Host "Target applications are monitored only; start them with their own launchers."
            exit 0
        } catch {
        }
    }
} finally {
    $client.Dispose()
}

$logDirectory = Join-Path $controllerRoot "runtime\logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

Start-Process -FilePath $python -ArgumentList @(
    "-u",
    (Join-Path $controllerRoot "feishu_bot.py")
) -WorkingDirectory $controllerRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDirectory "controller.log") `
    -RedirectStandardError (Join-Path $logDirectory "controller.log.err") | Out-Null

Write-Host "[controller] started; target applications will not be launched."

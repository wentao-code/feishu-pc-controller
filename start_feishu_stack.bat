@echo off
setlocal
cd /d "%~dp0"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_feishu_stack.ps1" %*
if errorlevel 1 (
    echo [ERROR] Unified Feishu plugin stack failed with exit code %errorlevel%.
    pause
)
endlocal

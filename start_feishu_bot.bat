@echo off
setlocal

call "%~dp0start_feishu_stack.bat" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Feishu plugin stack failed with exit code %EXIT_CODE%.
    pause
)

endlocal & exit /b %EXIT_CODE%

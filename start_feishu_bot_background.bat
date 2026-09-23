@echo off
setlocal

cd /d "%~dp0"
set "PYTHON_EXE="
if exist "%~dp0runtime\python-path.txt" set /p PYTHON_EXE=<"%~dp0runtime\python-path.txt"
if not defined PYTHON_EXE set "PYTHON_EXE=python"
"%PYTHON_EXE%" -u "%~dp0feishu_bot.py" >> "%~dp0feishu_bot.log" 2>&1
exit /b %errorlevel%

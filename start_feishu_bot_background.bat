@echo off
setlocal

cd /d "%~dp0"
set "PYTHON_EXE="
if exist "%~dp0runtime\python-path.txt" set /p PYTHON_EXE=<"%~dp0runtime\python-path.txt"
if not defined PYTHON_EXE set "PYTHON_EXE=python"
"%PYTHON_EXE%" -u "%~dp0run_feishu_bot.py" --stdout-log "%~dp0feishu_bot.log" --stderr-log "%~dp0feishu_bot.log"
exit /b %errorlevel%

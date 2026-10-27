@echo off
setlocal
set "TASK_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%TASK_PYTHON%" set "TASK_PYTHON=python"
"%TASK_PYTHON%" "%~dp0local.py" %*
if errorlevel 1 pause

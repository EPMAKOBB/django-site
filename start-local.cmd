@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Local Python was not found in .venv. See docs\recsys\exam_year_sandbox.md.
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -X utf8 "%~dp0scripts\start_local.py" %*
exit /b %errorlevel%

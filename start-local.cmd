@echo off
setlocal

rem Локальный запуск проекта на Windows.
rem При первом запуске scripts\start_local.py создаёт изолированную базу
rem PostgreSQL и остальные данные в .local, затем применяет миграции и
rem запускает Django. Production DATABASE_URL для этого не используется.

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Python was not found in .venv.
    echo Create it: py -m venv .venv
    echo Install packages: .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -X utf8 "%~dp0scripts\start_local.py" %*
exit /b %errorlevel%

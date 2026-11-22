@echo off
setlocal
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

if not exist "%PROJECT_DIR%venv\Scripts\python.exe" (
    echo Project Python was not found at "%PROJECT_DIR%venv\Scripts\python.exe"
    exit /b 2
)

"%PROJECT_DIR%venv\Scripts\python.exe" "%PROJECT_DIR%pipeline.py" >> "%PROJECT_DIR%scheduled_run.log" 2>&1
exit /b %ERRORLEVEL%

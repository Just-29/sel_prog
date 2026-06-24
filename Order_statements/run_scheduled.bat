@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=%~dp0..\venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "LOG=%~dp0logs\scheduled_run.log"
echo.>>"%LOG%"
echo [%date% %time%] Запуск по расписанию>>"%LOG%"

"%PYTHON%" -m script.main >>"%LOG%" 2>&1
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% neq 0 (
    echo [%date% %time%] Ошибка, код %EXIT_CODE%>>"%LOG%"
) else (
    echo [%date% %time%] Успешно>>"%LOG%"
)

exit /b %EXIT_CODE%

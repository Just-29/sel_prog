@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Настройка автозапуска Order_statements...
echo Настройки: %~dp0schedule.ini
echo.

set "PYTHON=%~dp0..\venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Для пробуждения ПК из сна рекомендуется запуск от имени администратора.
    echo.
)

"%PYTHON%" -m script.setup_schedule
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% neq 0 (
    echo Ошибка настройки. Код: %EXIT_CODE%
) else (
    echo Готово.
)

pause
exit /b %EXIT_CODE%

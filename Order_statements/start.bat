@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=%~dp0..\venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Не найден venv: %PYTHON%
    echo Установите зависимости: pip install -r requirements.txt
    set "PYTHON=python"
)

echo Запуск отправки заявлений Росреестр...
echo Python: %PYTHON%
echo CSV-файлы: %~dp0uploads_CSV
echo Лог результатов: %~dp0results.log
echo.

"%PYTHON%" -m script.main
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% neq 0 (
    echo Скрипт завершился с ошибкой. Код: %EXIT_CODE%
    echo Подробности: logs\errors.log и logs\diagnostics\
) else (
    echo Скрипт завершён успешно.
)

pause
exit /b %EXIT_CODE%

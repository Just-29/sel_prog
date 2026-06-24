@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Отключение автозапуска...
echo В schedule.ini будет установлено enabled=false
echo.

set "PYTHON=%~dp0..\venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" -c "from pathlib import Path; p=Path('schedule.ini'); t=p.read_text(encoding='utf-8'); import re; t=re.sub(r'(?m)^enabled\s*=.*','enabled=false',t) if re.search(r'(?m)^enabled\s*=',t) else t+'\nenabled=false\n'; p.write_text(t,encoding='utf-8')"

"%PYTHON%" -m script.setup_schedule
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% equ 0 (
    echo Автозапуск отключён. Чтобы снова включить — измените schedule.ini и запустите setup_schedule.bat
)

pause
exit /b %EXIT_CODE%


"""Точка входа: запуск браузера и обработка CSV из uploads_CSV."""
import atexit
import sys
from pathlib import Path

# Запуск как script/main.py или python -m script.main
if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from script.browser import create_driver, kill_chrome_processes
from script.logging_utils import (
    SESSION_ID,
    log_error,
    log_info,
    log_warning,
    write_session_report,
)
from script.login import login_funct
from script.native_dialogs import stop_native_dialog_watcher
from script.processor import run_processing_loop
from script.upload_queue import stage_files_from_future_uploads


def main():
    log_info(f"Сессия диагностики: {SESSION_ID}", stage="init")
    atexit.register(write_session_report)

    stage_files_from_future_uploads()

    kill_chrome_processes()
    driver = None
    try:
        driver, wait, _actions = create_driver()
        login_funct(driver)
        run_processing_loop(driver, wait)
    except Exception as e:
        log_error(
            "Критическая ошибка выполнения скрипта",
            stage="shutdown",
            exc=e,
            driver=driver,
            screenshot=True,
        )
        raise
    finally:
        stop_native_dialog_watcher()
        log_info("Скрипт завершён", stage="shutdown")
        try:
            write_session_report()
        except Exception as e:
            log_warning("Не удалось записать итоговый отчёт сессии", stage="shutdown", exc=e)
        if driver is not None:
            try:
                driver.quit()
            except Exception as e:
                log_warning("Ошибка при закрытии WebDriver", stage="shutdown", exc=e)


if __name__ == "__main__":
    main()

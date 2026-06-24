"""Сессия, модальные окна и утилиты страницы."""
import time
from pathlib import Path

from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .constants import ADDRESS_INPUT_XPATH, MAX_FILE_ATTEMPTS, SESSION_EXPIRED_MARKERS
from .logging_utils import (
    log_error,
    log_exception,
    log_info,
    log_scenario,
    log_warning,
    save_selenium_note,
)
from .login import login_funct

def close_modal_window(driver):
    """Закрывает мешающие модальные окна"""
    stage = "close_modal"
    try:
        close_buttons = driver.find_elements("xpath", "//button[contains(@class, 'rros-ui-lib-modal__close-btn')]")
        if close_buttons:
            driver.execute_script("arguments[0].click();", close_buttons[0])
            log_info("Модальное окно закрыто через крестик", stage=stage)
            time.sleep(2)
            return True
            
        cancel_buttons = driver.find_elements("xpath", "//button[contains(text(), 'Отмена') or contains(text(), 'Закрыть') or contains(text(), 'Cancel')]")
        if cancel_buttons:
            driver.execute_script("arguments[0].click();", cancel_buttons[0])
            log_info("Модальное окно закрыто через кнопку отмены", stage=stage)
            time.sleep(2)
            return True
            
        driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', {'key': 'Escape'}));")
        log_info("Отправлен ESC через JavaScript", stage=stage)
        time.sleep(2)
        
        if not driver.find_elements("xpath", "//div[contains(@class, 'rros-ui-lib-modal__window')]"):
            return True
        else:
            log_warning("ESC не закрыл модальное окно", stage=stage, driver=driver)
            return False
            
    except Exception as e:
        log_exception(stage, e, driver=driver, message="Ошибка при закрытии модального окна")
        return False


def is_session_expired(driver):
    """Проверяет сообщение «Время сессии истекло» на странице."""
    if driver is None:
        return False
    try:
        xpaths = (
            "//div[contains(@class, 'rros-ui-lib-error-message')]",
            "//div[contains(@class, 'rros-ui-lib-error')]",
            "//div[contains(@class, 'rros-ui-lib-errors')]",
        )
        for xpath in xpaths:
            for el in driver.find_elements("xpath", xpath):
                text = (el.text or "").strip()
                if text and any(marker in text for marker in SESSION_EXPIRED_MARKERS):
                    return True
    except Exception:
        pass
    return False


def recover_session_if_expired(driver, stage="session"):
    """Повторная авторизация при истечении сессии. Возвращает True, если сессия была восстановлена."""
    if not is_session_expired(driver):
        return False
    log_scenario(
        "session_expired", stage, driver=driver, screenshot=True,
        message="Время сессии истекло — выполняется повторная авторизация",
        recommendation="После входа скрипт повторит обработку текущего файла",
    )
    login_funct(driver)
    time.sleep(3)
    return True

def delete_local_csv_file(csv_path, stage="result"):
    """Удаляет локальный CSV после успешной отправки заявки."""
    try:
        path = Path(csv_path)
        if path.is_file():
            path.unlink()
            log_info(f"Локальный CSV удалён: {path.name}", stage=stage, file=path.name)
            return True
    except Exception as e:
        log_warning(
            f"Не удалось удалить локальный CSV: {Path(csv_path).name}",
            stage=stage, exc=e,
        )
    return False


def record_file_send_failure(driver, upload_file, file_attempt, reason, exc=None, stage="main_loop"):
    """Логирует неудачную отправку файла. Возвращает True, если будет повтор."""
    will_retry = file_attempt < MAX_FILE_ATTEMPTS
    attempt_label = f"попытка {file_attempt}/{MAX_FILE_ATTEMPTS}"
    detail = f"{reason} ({attempt_label})"
    note = f"ОШИБКА: Файл {upload_file} не отправлен — {detail}"
    if exc is not None:
        note += f" — {type(exc).__name__}: {exc}"
    save_selenium_note(driver, note)
    if exc is not None:
        log_exception(stage, exc, driver=driver, message=detail, file=upload_file.name, will_retry=will_retry)
    else:
        log_error(detail, stage=stage, driver=driver, file=upload_file.name, will_retry=will_retry)
    if will_retry:
        log_info(
            f"Повторная отправка файла {upload_file.name} "
            f"(следующая попытка {file_attempt + 1}/{MAX_FILE_ATTEMPTS}) через 5 сек",
            stage="main_loop", file=upload_file.name,
        )
        time.sleep(5)
    else:
        log_error(
            f"Файл {upload_file.name} пропущен: исчерпан лимит {MAX_FILE_ATTEMPTS} попыток",
            stage="main_loop", file=upload_file.name, reason=reason,
        )
    return will_retry
def is_page_loaded(driver):
    try:
        return driver.execute_script("return document.readyState") == "complete"
    except Exception as e:
        log_warning("Не удалось проверить readyState страницы", stage="page_load", exc=e)
        return False

def is_modal_loaded(driver):
    """Проверка что модальное окно полностью загружено"""
    try:
        modal_visible = EC.visibility_of_element_located((
            "xpath", "//div[contains(@class, 'modal')] | //div[contains(@class, 'rros-ui-lib-modal')]"
        ))
        input_ready = EC.presence_of_element_located(("xpath", ADDRESS_INPUT_XPATH))

        return modal_visible(driver) and input_ready(driver)
    except Exception as e:
        log_warning("Модальное окно не загружено", stage="modal_check", exc=e, driver=driver)
        return False


def wait_for_all_loadings(driver):
    """Ожидание исчезновения всех loading-индикаторов"""
    stage = "loading_wait"
    load_selectors = [
        "//div[contains(@class, 'loading')]",
        "//div[contains(@class, 'spinner')]",
        "//div[contains(@class, 'rros-ui-lib-loading')]",
        "//*[contains(text(), 'Загрузка')]",
        "//*[contains(text(), 'Loading')]"
    ]
    
    for selector in load_selectors:
        try:
            WebDriverWait(driver, 10).until(EC.invisibility_of_element_located(("xpath", selector)))
            log_info(f"Loading исчез: {selector}", stage=stage)
        except Exception as e:
            log_warning(
                f"Loading не найден или не исчез: {selector}",
                stage=stage, exc=e,
            )
    
    time.sleep(1)

"""Авторизация через ЭЦП."""
import os
import time

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .constants import (
    FORM_PAGE_URL,
    LOGIN_CONTINUE_XPATHS,
    LOGIN_EDS_BUTTON_XPATHS,
    LOGIN_EDS_SCREEN_XPATHS,
    LOGIN_MINISTRY_XPATHS,
    LOGIN_ROLE_LIST_XPATH,
    LOGIN_ROLE_XPATHS,
    SESSION_EXPIRED_MARKERS,
)
from .logging_utils import log_error, log_info, log_warning
from .native_dialogs import (
    dismiss_pending_native_dialogs,
    pulse_cryptopro_access,
    pulse_gosplugin_dialogs,
    pulse_native_dialogs,
    restart_native_dialog_watcher,
    start_native_dialog_watcher,
)

_LOGIN_PULSE_SEC = 10
_LOGIN_UI_WAIT_SEC = 45
_SESSION_CHECK_GRACE_SEC = 2.5
_LAST_LOGIN_REFRESH_AT = 0.0
_ROLE_PULSE_SEC = 45
_ROLE_WAIT_SEC = 120
_SESSION_EXPIRED_RECOVERIES_MAX = 5
_ROSREESTR_LOGIN_URL = FORM_PAGE_URL

# Этапы входа через ЕСИА (от раннего к позднему).
_LOGIN_STEPS = (
    ("eds_button", LOGIN_EDS_BUTTON_XPATHS, "Нажата кнопка электронной подписи", False, 3),
    ("continue", LOGIN_CONTINUE_XPATHS, "Нажата кнопка Продолжить", False, 3),
    ("ministry", LOGIN_MINISTRY_XPATHS, "Выбрано МИНИСТЕРСТВО ЖКХ", False, 5),
    ("role", LOGIN_ROLE_XPATHS, "Выбран пользователь (ЭП)", True, 5),
)
_LOGIN_STEP_INDEX = {name: idx for idx, (name, *_rest) in enumerate(_LOGIN_STEPS)}
_EDS_SCREEN_XPATH = " | ".join(f"({xpath})" for xpath in LOGIN_EDS_SCREEN_XPATHS)


class LoginSessionExpired(Exception):
    """Сессия ЕСИА/Росреестра истекла — страница обновлена, нужно продолжить вход."""


def _login_form_loaded(driver):
    return bool(driver.find_elements("xpath", "//input[@id='applicantCategory']"))


def _on_rosreestr_login_page(driver) -> bool:
    try:
        url = (driver.current_url or "").lower()
    except Exception:
        return False
    return "lk.rosreestr.ru" in url and "/login" in url


def _on_esia_login_page(driver) -> bool:
    try:
        url = (driver.current_url or "").lower()
    except Exception:
        return False
    return "esia.gosuslugi.ru" in url and "/login" in url


def is_login_complete(driver) -> bool:
    return _login_form_loaded(driver) and not _on_esia_login_page(driver)


def _xpath_any_visible(driver, xpaths) -> bool:
    combined = " | ".join(f"({xpath})" for xpath in xpaths)
    for el in driver.find_elements("xpath", combined):
        try:
            if el.is_displayed():
                return True
        except Exception:
            pass
    return False


def _role_selector_visible(driver) -> bool:
    if _xpath_any_visible(driver, LOGIN_ROLE_XPATHS):
        return True
    return _xpath_any_visible(
        driver,
        (
            "//button[contains(@class, 'role-selector-list__item')]",
            *LOGIN_ROLE_LIST_XPATH,
        ),
    )


def _login_ui_ready(driver) -> bool:
    if is_login_complete(driver):
        return True
    if _role_selector_visible(driver):
        return True
    if driver.find_elements("xpath", _EDS_SCREEN_XPATH):
        return True
    if _xpath_any_visible(driver, LOGIN_EDS_BUTTON_XPATHS):
        return True
    if _xpath_any_visible(driver, LOGIN_CONTINUE_XPATHS):
        return True
    if _xpath_any_visible(driver, LOGIN_MINISTRY_XPATHS):
        return True
    return False


def _wait_for_login_ui(driver, timeout: float | None = None) -> bool:
    if timeout is None:
        timeout = float(os.getenv("LOGIN_UI_WAIT_SEC", str(_LOGIN_UI_WAIT_SEC)))
    if _login_ui_ready(driver):
        return True
    log_info("Ожидание загрузки экрана входа", stage="login")
    try:
        WebDriverWait(driver, timeout).until(lambda d: _login_ui_ready(d))
        return True
    except TimeoutException:
        return False


def _wait_for_role_selector(driver, timeout: float | None = None) -> bool:
    if _role_selector_visible(driver):
        return True
    if not (_on_rosreestr_login_page(driver) or _on_esia_login_page(driver)):
        return False
    if timeout is None:
        timeout = float(os.getenv("LOGIN_ROLE_WAIT_SEC", str(_ROLE_WAIT_SEC)))
    log_info("Ожидание списка ролей ЕСИА", stage="login")
    try:
        WebDriverWait(driver, timeout).until(lambda d: _role_selector_visible(d))
        return True
    except TimeoutException:
        return False


def _click_login_element(driver, el) -> None:
    """Клик по элементу входа: scroll, button-родитель для роли, обычный/JS клик."""
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
    time.sleep(0.2)
    for xpath in (
        "./ancestor::button[contains(@class, 'role-selector-list__item')][1]",
        "./ancestor::div[contains(@class, 'role-selector-list__item-content')][1]",
    ):
        try:
            target = el.find_element("xpath", xpath)
            try:
                target.click()
                return
            except Exception:
                driver.execute_script("arguments[0].click();", target)
                return
        except Exception:
            pass
    try:
        el.click()
        return
    except Exception:
        pass
    driver.execute_script("arguments[0].click();", el)


def _click_role_selector(
    driver,
    stage: str,
    *,
    landing_url: str | None = None,
    recovery_counter: list | None = None,
    label: str = "Выбор пользователя",
) -> bool:
    """Выбирает организацию в списке ролей ЕСИА. Возвращает True, если шаг выполнен."""
    combined = " | ".join(f"({xpath})" for xpath in LOGIN_ROLE_XPATHS)
    for el in driver.find_elements("xpath", combined):
        try:
            if not el.is_displayed():
                continue
        except Exception:
            continue
        _click_login_element(driver, el)
        return _wait_login_click_result(
            driver, "role", stage, landing_url, recovery_counter, label,
        )
    return False


def _step_still_pending(driver, step_name: str) -> bool:
    if step_name == "eds_button":
        return _xpath_any_visible(driver, LOGIN_EDS_BUTTON_XPATHS)
    if step_name == "continue":
        return _xpath_any_visible(driver, LOGIN_CONTINUE_XPATHS)
    if step_name == "ministry":
        return _xpath_any_visible(driver, LOGIN_MINISTRY_XPATHS)
    if step_name == "role":
        return _role_selector_visible(driver)
    return False


def _login_step_progressed(driver, step_name: str) -> bool:
    """Клик сработал: появился следующий экран или текущий шаг исчез."""
    if is_login_complete(driver):
        return True
    if step_name == "eds_button":
        return (
            not _xpath_any_visible(driver, LOGIN_EDS_BUTTON_XPATHS)
            or _xpath_any_visible(driver, LOGIN_CONTINUE_XPATHS)
            or _xpath_any_visible(driver, LOGIN_MINISTRY_XPATHS)
            or _role_selector_visible(driver)
        )
    if step_name == "continue":
        return (
            not _xpath_any_visible(driver, LOGIN_CONTINUE_XPATHS)
            or _xpath_any_visible(driver, LOGIN_MINISTRY_XPATHS)
            or _role_selector_visible(driver)
        )
    if step_name == "ministry":
        return (
            _role_selector_visible(driver)
            or not _xpath_any_visible(driver, LOGIN_MINISTRY_XPATHS)
        )
    if step_name == "role":
        return not _role_selector_visible(driver)
    return True


def _maybe_recover_session_expired(
    driver,
    stage: str,
    landing_url: str | None,
    recovery_counter: list | None,
    label: str,
) -> None:
    if not _is_login_session_expired(driver):
        return
    recoveries = recovery_counter[0] if recovery_counter else 0
    if recoveries >= _SESSION_EXPIRED_RECOVERIES_MAX:
        raise TimeoutException(f"{label} — лимит восстановлений сессии")
    if recovery_counter is not None:
        recovery_counter[0] += 1
    _recover_login_session_expired(
        driver, stage, landing_url or _ROSREESTR_LOGIN_URL,
        recovery_no=recoveries + 1,
    )


def _wait_login_click_result(
    driver,
    step_name: str,
    stage: str,
    landing_url: str | None,
    recovery_counter: list | None,
    label: str,
) -> bool:
    """
    После клика ждём реакцию страницы.
    Ошибка «сессия истекла» часто появляется только после клика и отменяет действие.
  """
    settle = float(os.getenv("LOGIN_POST_CLICK_SETTLE_SEC", "4"))
    poll = float(os.getenv("LOGIN_DIALOG_POLL_SEC", "0.35"))
    deadline = time.time() + settle

    while time.time() < deadline:
        dismiss_pending_native_dialogs()
        _maybe_recover_session_expired(
            driver, stage, landing_url, recovery_counter, label,
        )
        if _login_step_progressed(driver, step_name):
            return True
        time.sleep(poll)

    _maybe_recover_session_expired(
        driver, stage, landing_url, recovery_counter, label,
    )
    return _login_step_progressed(driver, step_name)


def _text_indicates_session_expired(text: str) -> bool:
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in SESSION_EXPIRED_MARKERS):
        return True
    if "сесс" in lowered and "обновите страницу" in lowered:
        return True
    if "сесс" in lowered and "истек" in lowered:
        return True
    return False


def _is_login_session_expired(driver) -> bool:
    """Видимое сообщение «Время сессии истекло» на ЕСИА или Росреестре."""
    if driver is None:
        return False
    grace = float(os.getenv("LOGIN_SESSION_CHECK_GRACE_SEC", str(_SESSION_CHECK_GRACE_SEC)))
    if time.time() - _LAST_LOGIN_REFRESH_AT < grace:
        return False
    try:
        xpaths = (
            "//div[contains(@class, 'rros-ui-lib-error-message')]",
            "//div[contains(@class, 'rros-ui-lib-errors')]",
            "//div[contains(@class, 'esia') and contains(@class, 'error')]",
            "//div[contains(@class, 'toast')]",
            "//div[contains(@class, 'notification')]",
        )
        for xpath in xpaths:
            for el in driver.find_elements("xpath", xpath):
                try:
                    if not el.is_displayed():
                        continue
                except Exception:
                    continue
                text = (el.text or "").strip()
                if not text or len(text) > 400:
                    continue
                if _text_indicates_session_expired(text):
                    return True
    except Exception:
        pass
    return False


def _refresh_login_page(driver, landing_url: str | None = None) -> None:
    """Обновляет текущую страницу (F5, с кэшем) после истечения сессии."""
    global _LAST_LOGIN_REFRESH_AT
    try:
        driver.refresh()
    except Exception:
        if landing_url:
            driver.get(landing_url)
    _LAST_LOGIN_REFRESH_AT = time.time()
    time.sleep(3)
    try:
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        pass


def _detect_login_stage(driver) -> str:
    """Определяет текущий этап входа для продолжения после обновления страницы."""
    if is_login_complete(driver):
        return "complete"
    if _role_selector_visible(driver):
        return "role"
    if _xpath_any_visible(driver, LOGIN_MINISTRY_XPATHS):
        return "ministry"
    if _xpath_any_visible(driver, LOGIN_CONTINUE_XPATHS):
        return "continue"
    if _xpath_any_visible(driver, LOGIN_EDS_BUTTON_XPATHS):
        return "eds_button"
    if driver.find_elements("xpath", _EDS_SCREEN_XPATH):
        return "eds_screen"
    if _on_esia_login_page(driver):
        return "esia_login"
    if _on_rosreestr_login_page(driver):
        return "rosreestr_login"
    return "initial"


def _login_step_start_index(login_stage: str) -> int:
    if login_stage in _LOGIN_STEP_INDEX:
        return _LOGIN_STEP_INDEX[login_stage]
    if login_stage == "rosreestr_login":
        return _LOGIN_STEP_INDEX["role"]
    if login_stage in ("eds_screen", "esia_login", "initial"):
        return 0
    return 0


def _resume_login_after_session_refresh(
    driver, wait, stage: str, landing_url: str, recovery_counter: list | None = None,
) -> bool:
    """После F5 ждём загрузку и продолжаем с фактического экрана (не со следующего шага)."""
    _wait_for_login_ui(driver, wait._timeout)
    detected = _detect_login_stage(driver)
    log_info(
        "Продолжение входа после обновления страницы",
        stage=stage,
        login_step=detected,
    )
    if detected == "complete":
        return True
    if detected in ("role", "rosreestr_login"):
        return _attempt_role_selection(
            driver, wait, stage, landing_url, recovery_counter=recovery_counter,
        )
    if detected not in ("initial", "esia_login"):
        _login_via_eds(
            driver, wait, stage, landing_url,
            start_from=detected, recovery_counter=recovery_counter,
        )
        return is_login_complete(driver)
    if _on_rosreestr_login_page(driver):
        return _attempt_role_selection(
            driver, wait, stage, landing_url, recovery_counter=recovery_counter,
        )
    return is_login_complete(driver)


def _recover_login_session_expired(
    driver, stage: str, landing_url: str, *, recovery_no: int,
) -> None:
    global _LAST_LOGIN_REFRESH_AT
    before = _detect_login_stage(driver)
    log_warning(
        "Время сессии истекло — обновление страницы и продолжение входа",
        stage=stage,
        driver=driver,
        login_step=before,
        recovery=recovery_no,
    )
    _refresh_login_page(driver, landing_url)
    if _detect_login_stage(driver) == "initial" and landing_url:
        driver.get(landing_url)
        _LAST_LOGIN_REFRESH_AT = time.time()
        time.sleep(3)
    _wait_for_login_ui(driver, _LOGIN_UI_WAIT_SEC)
    after = _detect_login_stage(driver)
    log_info(
        "После обновления страницы вход продолжается с фактического этапа",
        stage=stage,
        login_step=after,
        login_step_before=before,
        recovery=recovery_no,
    )
    raise LoginSessionExpired()


def _dismiss_native_dialogs(*, extended: bool = False) -> None:
    if extended:
        pulse_gosplugin_dialogs(_ROLE_PULSE_SEC)
        pulse_cryptopro_access(_ROLE_PULSE_SEC)
        pulse_native_dialogs(8)
        return
    pulse_gosplugin_dialogs(_LOGIN_PULSE_SEC)
    pulse_cryptopro_access(_LOGIN_PULSE_SEC)
    pulse_native_dialogs(5)


def _login_wait_click(
    driver, wait, xpaths, stage, label, step_name,
    *, landing_url: str | None = None, recovery_counter: list | None = None,
):
    combined = " | ".join(f"({xpath})" for xpath in xpaths)
    deadline = time.time() + wait._timeout
    poll = float(os.getenv("LOGIN_DIALOG_POLL_SEC", "0.35"))

    while time.time() < deadline:
        _maybe_recover_session_expired(
            driver, stage, landing_url, recovery_counter, label,
        )
        try:
            el = WebDriverWait(driver, 1).until(
                EC.element_to_be_clickable(("xpath", combined))
            )
            _click_login_element(driver, el)
            if _wait_login_click_result(
                driver, step_name, stage, landing_url, recovery_counter, label,
            ):
                log_info(label, stage=stage)
                return
        except TimeoutException:
            pass
        time.sleep(poll)

    raise TimeoutException(f"{label} — таймаут {wait._timeout} сек")


def _login_wait_click_with_dialogs(
    driver, xpaths, stage, label, step_name, total_timeout=None,
    *, landing_url: str | None = None, recovery_counter: list | None = None,
):
    """
    Ждёт элемент, параллельно закрывая окна Госплагин/КриптоПро.
    Не блокируется на WebDriverWait — диалоги на другом мониторе обрабатываются в цикле.
    """
    if total_timeout is None:
        total_timeout = _ROLE_WAIT_SEC

    combined = " | ".join(f"({xpath})" for xpath in xpaths)
    deadline = time.time() + total_timeout
    poll = float(os.getenv("LOGIN_DIALOG_POLL_SEC", "0.35"))
    role_step = step_name == "role"

    while time.time() < deadline:
        _maybe_recover_session_expired(
            driver, stage, landing_url, recovery_counter, label,
        )

        if role_step and _role_selector_visible(driver):
            if _click_role_selector(
                driver, stage,
                landing_url=landing_url,
                recovery_counter=recovery_counter,
                label=label,
            ):
                log_info(label, stage=stage)
                dismiss_pending_native_dialogs()
                return

        dismiss_pending_native_dialogs()
        try:
            el = WebDriverWait(driver, 1).until(
                EC.element_to_be_clickable(("xpath", combined))
            )
            _click_login_element(driver, el)
            if _wait_login_click_result(
                driver, step_name, stage, landing_url, recovery_counter, label,
            ):
                log_info(label, stage=stage)
                dismiss_pending_native_dialogs()
                return
        except TimeoutException:
            pass
        time.sleep(poll)

    if role_step and _role_selector_visible(driver):
        raise TimeoutException(
            f"{label} — список ролей ЕСИА всё ещё на экране (таймаут {total_timeout} сек)"
        )
    raise TimeoutException(f"{label} — таймаут {total_timeout} сек")


def _login_via_eds(
    driver, wait, stage, landing_url: str, start_from: str | None = None,
    recovery_counter: list | None = None,
):
    if recovery_counter is None:
        recovery_counter = [0]
    start_idx = _login_step_start_index(start_from or _detect_login_stage(driver))

    while True:
        try:
            for step_idx, (_step_name, xpaths, label, with_dialogs, pause_sec) in enumerate(
                _LOGIN_STEPS
            ):
                if step_idx < start_idx:
                    continue
                if with_dialogs:
                    restart_native_dialog_watcher()
                    _login_wait_click_with_dialogs(
                        driver, xpaths, stage, label, _step_name,
                        landing_url=landing_url,
                        recovery_counter=recovery_counter,
                    )
                    if _step_name != "role" or not _role_selector_visible(driver):
                        _dismiss_native_dialogs(extended=True)
                else:
                    _login_wait_click(
                        driver, wait, xpaths, stage, label, _step_name,
                        landing_url=landing_url,
                        recovery_counter=recovery_counter,
                    )
                    _dismiss_native_dialogs()
                time.sleep(pause_sec)
            return
        except LoginSessionExpired:
            if _resume_login_after_session_refresh(
                driver, wait, stage, landing_url, recovery_counter,
            ):
                return
            start_idx = _login_step_start_index(_detect_login_stage(driver))
            if _detect_login_stage(driver) == "complete":
                return


def _attempt_role_selection(
    driver, wait, stage: str, landing_url: str, *,
    label: str = "Выбран пользователь (без ЭП)",
    recovery_counter: list | None = None,
) -> bool:
    if recovery_counter is None:
        recovery_counter = [0]
    if not _wait_for_role_selector(driver, _ROLE_WAIT_SEC):
        return False
    if not _role_selector_visible(driver):
        return False
    try:
        restart_native_dialog_watcher()
        _login_wait_click_with_dialogs(
            driver, LOGIN_ROLE_XPATHS, stage, label, "role",
            landing_url=landing_url,
            recovery_counter=recovery_counter,
        )
        if not _role_selector_visible(driver):
            _dismiss_native_dialogs(extended=True)
        time.sleep(3)
        return is_login_complete(driver) or not _role_selector_visible(driver)
    except LoginSessionExpired:
        return _resume_login_after_session_refresh(
            driver, wait, stage, landing_url, recovery_counter,
        )
    except Exception as e:
        if is_login_complete(driver):
            log_info("Форма доступна, выбор пользователя не потребовался", stage=stage)
            return True
        log_warning(
            "Не удалось выбрать пользователя",
            stage=stage, exc=e, driver=driver, capture_diagnostics=True,
        )
        return False


def _continue_login_from_screen(driver, wait, stage: str, landing_url: str) -> None:
    _wait_for_login_ui(driver, wait._timeout)
    detected = _detect_login_stage(driver)
    log_info("Экран входа определён", stage=stage, login_step=detected)

    if detected == "complete":
        return
    if detected == "role" or detected == "rosreestr_login":
        _attempt_role_selection(driver, wait, stage, landing_url)
        return
    if detected not in ("initial", "esia_login"):
        try:
            _login_via_eds(driver, wait, stage, landing_url, start_from=detected)
        except LoginSessionExpired:
            _resume_login_after_session_refresh(driver, wait, stage, landing_url)
        except Exception as e:
            log_warning(
                "Не удалось завершить вход с текущего этапа",
                stage=stage, exc=e, driver=driver, capture_diagnostics=True,
            )
        return
    if _on_rosreestr_login_page(driver):
        _attempt_role_selection(driver, wait, stage, landing_url)


def _ensure_logged_in(driver, wait, stage: str, landing_url: str) -> None:
    if is_login_complete(driver):
        log_info("Авторизация завершена", stage=stage)
        return

    if _on_esia_login_page(driver):
        log_warning(
            "Остались на странице входа ЕСИА — повторная попытка авторизации",
            stage=stage,
            driver=driver,
        )
        try:
            if driver.find_elements("xpath", _EDS_SCREEN_XPATH) or _detect_login_stage(driver) != "initial":
                _login_via_eds(driver, wait, stage, landing_url)
        except LoginSessionExpired:
            _resume_login_after_session_refresh(driver, wait, stage, landing_url)
        except Exception as e:
            log_warning("Повторная авторизация через ЭП не удалась", stage=stage, exc=e, driver=driver)

    if is_login_complete(driver):
        log_info("Авторизация завершена после повторной попытки", stage=stage)
        return

    if _on_rosreestr_login_page(driver) or _role_selector_visible(driver):
        log_warning(
            "Остались на странице выбора роли — повторная попытка",
            stage=stage,
            driver=driver,
        )
        if _attempt_role_selection(driver, wait, stage, landing_url):
            if is_login_complete(driver):
                log_info("Авторизация завершена после выбора роли", stage=stage)
                return

    detected = _detect_login_stage(driver)
    if detected not in ("complete", "initial", "esia_login", "rosreestr_login"):
        log_warning(
            "Авторизация не завершена — повтор шага входа на странице",
            stage=stage,
            login_step=detected,
            driver=driver,
        )
        try:
            _login_via_eds(driver, wait, stage, landing_url, start_from=detected)
        except LoginSessionExpired:
            _resume_login_after_session_refresh(driver, wait, stage, landing_url)
        except Exception as e:
            log_warning(
                "Повтор шага входа не удался",
                stage=stage, exc=e, driver=driver,
            )
        if is_login_complete(driver):
            log_info("Авторизация завершена после повтора шага входа", stage=stage)
            return

    log_warning(
        "Финальная попытка закрыть окна Госплагин перед проверкой авторизации",
        stage=stage,
    )
    pulse_gosplugin_dialogs(15)
    pulse_cryptopro_access(10)
    if is_login_complete(driver):
        log_info("Авторизация завершена после финального закрытия окон", stage=stage)
        return

    if _role_selector_visible(driver):
        msg = "Авторизация не завершена — не выбрана роль в списке ЕСИА"
        err = "Авторизация не завершена: не удалось выбрать организацию в списке ролей"
    else:
        msg = "Авторизация не завершена — форма Росреестра недоступна (возможно, не принято окно Госплагин)"
        err = "Авторизация не завершена: не удалось принять окно подтверждения Госплагин/КриптоПро"

    log_error(
        msg,
        stage=stage,
        driver=driver,
        capture_diagnostics=True,
    )
    raise RuntimeError(err)


def login_funct(driver):
    global _LAST_LOGIN_REFRESH_AT
    stage = "login"
    start_native_dialog_watcher()
    wait_short = WebDriverWait(driver, 3)
    wait = WebDriverWait(driver, 20)
    url = _ROSREESTR_LOGIN_URL

    driver.get(url)
    _LAST_LOGIN_REFRESH_AT = time.time()
    log_info("Переход на страницу Росреестра", stage=stage, url=url)
    time.sleep(3)

    if is_login_complete(driver):
        log_info("Форма уже загружена, авторизация не требуется", stage=stage)
        return

    try:
        if wait_short.until(EC.presence_of_element_located(
            ("xpath", "//h1[contains(.,'Не удается получить доступ к сайту')]")
        )):
            log_warning("Сайт недоступен, повторный переход", stage=stage, driver=driver)
            driver.get(url)
            time.sleep(3)
    except TimeoutException:
        pass

    login_started = False
    try:
        if wait_short.until(EC.visibility_of_element_located(("xpath", _EDS_SCREEN_XPATH))):
            if driver.find_elements("xpath", "//h1[contains(., 'QR-код')]"):
                log_info("Экран входа: QR-код", stage=stage)
            else:
                log_info("Экран входа: восстановление", stage=stage)
            login_started = True
            _login_via_eds(driver, wait, stage, url)
    except LoginSessionExpired:
        login_started = True
        _resume_login_after_session_refresh(driver, wait, stage, url)
    except TimeoutException:
        if login_started:
            log_warning(
                "Авторизация через ЭП прервана (таймаут шага — проверьте окно Госплагин)",
                stage=stage,
                driver=driver,
            )
        else:
            log_info("Экран восстановления/QR не найден", stage=stage)
    except Exception as e:
        log_warning("Ошибка при авторизации через ЭП", stage=stage, exc=e, driver=driver)

    if is_login_complete(driver):
        log_info("Форма загружена после входа", stage=stage)
        return

    _continue_login_from_screen(driver, wait, stage, url)

    _ensure_logged_in(driver, wait, stage, url)

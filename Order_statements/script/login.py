
"""Авторизация через ЭЦП."""
import time

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .constants import (
    LOGIN_CONTINUE_XPATHS,
    LOGIN_EDS_BUTTON_XPATHS,
    LOGIN_EDS_SCREEN_XPATHS,
    LOGIN_MINISTRY,
    LOGIN_MINISTRY_FULL,
    LOGIN_MINISTRY_XPATHS,
    LOGIN_ROLE_XPATHS,
)
from .logging_utils import log_info, log_warning
from .native_dialogs import pulse_cryptopro_access, pulse_native_dialogs, start_native_dialog_watcher

def _login_form_loaded(driver):
    return bool(driver.find_elements("xpath", "//input[@id='applicantCategory']"))


def _login_wait_click(wait, xpaths, stage, label):
    combined = " | ".join(f"({xpath})" for xpath in xpaths)
    wait.until(EC.element_to_be_clickable(("xpath", combined))).click()
    log_info(label, stage=stage)


def _login_via_eds(driver, wait, stage):
    _login_wait_click(wait, LOGIN_EDS_BUTTON_XPATHS, stage, "Нажата кнопка электронной подписи")
    pulse_cryptopro_access()
    pulse_native_dialogs()
    time.sleep(5)
    _login_wait_click(wait, LOGIN_CONTINUE_XPATHS, stage, "Нажата кнопка Продолжить")
    pulse_cryptopro_access()
    pulse_native_dialogs()
    time.sleep(5)
    _login_wait_click(wait, LOGIN_MINISTRY_XPATHS, stage, "Выбрано МИНИСТЕРСТВО ЖКХ")
    pulse_cryptopro_access()
    pulse_native_dialogs()
    time.sleep(10)
    _login_wait_click(wait, LOGIN_ROLE_XPATHS, stage, "Выбран пользователь (ЭП)")
    # После выбора сертификата/роли чаще всего появляются 1–2 окна «Подтверждение доступа»
    pulse_cryptopro_access(30)
    pulse_native_dialogs()
    time.sleep(5)


def login_funct(driver):
    stage = "login"
    start_native_dialog_watcher()
    wait_short = WebDriverWait(driver, 3)
    wait = WebDriverWait(driver, 15)
    url = "https://lk.rosreestr.ru/eservices/request-info-from-egrn/real-estate-object-or-its-rightholder"

    driver.get(url)
    log_info("Переход на страницу Росреестра", stage=stage, url=url)
    time.sleep(3)

    if _login_form_loaded(driver):
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

    # Авторизация через ЭП (экран «Восстановить» или «Вход по QR-коду»)
    try:
        eds_screen = " | ".join(f"({xpath})" for xpath in LOGIN_EDS_SCREEN_XPATHS)
        if wait_short.until(EC.visibility_of_element_located(("xpath", eds_screen))):
            if driver.find_elements("xpath", "//h1[contains(., 'QR-код')]"):
                log_info("Экран входа: QR-код", stage=stage)
            else:
                log_info("Экран входа: восстановление", stage=stage)
            _login_via_eds(driver, wait, stage)
            return
    except TimeoutException:
        log_info("Экран восстановления/QR не найден", stage=stage)
    except Exception as e:
        log_warning("Ошибка при авторизации через ЭП", stage=stage, exc=e, driver=driver)

    if _login_form_loaded(driver):
        log_info("Форма загружена после входа", stage=stage)
        return

    try:
        _login_wait_click(wait, LOGIN_ROLE_XPATHS, stage, "Выбран пользователь (без ЭП)")
        time.sleep(5)
    except Exception as e:
        if _login_form_loaded(driver):
            log_info("Форма доступна, выбор пользователя не потребовался", stage=stage)
        else:
            log_warning(
                "Не удалось выбрать пользователя, продолжаем работу",
                stage=stage, exc=e, driver=driver, capture_diagnostics=True,
            )


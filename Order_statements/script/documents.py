"""Документы полномочий и тип выписки."""
import time

from selenium.common.exceptions import (
    ElementNotInteractableException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .applicant import (
    _page_has_single_value_marker,
    _react_select_display_text,
    _wait_react_select_options,
    is_applicant_category_filled,
)
from .address import is_address_filled_on_form
from .config import CORRECTION, DOCUMENT_DATE, DOCUMENT_NUMBER, ISSUING_AUTHORITY
from .constants import AUTHORITY_DOCUMENT_TYPE, VIPISKA_MARKER, VIPISKA_TEXT
from .logging_utils import log_info, log_warning

def _input_already_has_value(current, expected):
    """Поле уже содержит нужное значение — повторный ввод не нужен."""
    if not current:
        return False
    if current == expected:
        return True
    if expected and expected in current and len(current) <= len(expected) + 5:
        return True
    return False


def _set_input_if_needed(drv, field_id, value, stage="documents"):
    if not value:
        return False
    el = drv.find_element("xpath", f"//input[@id='{field_id}']")
    current = (el.get_attribute("value") or "").strip()
    if _input_already_has_value(current, value):
        log_info(f"Поле уже заполнено, пропуск", stage=stage, field=field_id, current=current[:80])
        return True
    if current:
        el.clear()
        time.sleep(0.2)
    el.send_keys(value)
    log_info(f"Поле заполнено", stage=stage, field=field_id, value=value[:80])
    return True


def is_authority_document_type_filled(drv):
    display = _react_select_display_text(drv, "userAuthorityConfirmationDocument.documentType")
    if AUTHORITY_DOCUMENT_TYPE in display:
        return True
    return _page_has_single_value_marker(drv, AUTHORITY_DOCUMENT_TYPE)


def _authority_document_text_fields_filled(drv):
    for field_id, expected in (
        ("userAuthorityConfirmationDocument.documentNumber", DOCUMENT_NUMBER),
        ("userAuthorityConfirmationDocument.documentIssueDate", DOCUMENT_DATE),
        ("userAuthorityConfirmationDocument.issuingAuthority", ISSUING_AUTHORITY),
    ):
        if not expected:
            continue
        try:
            current = (drv.find_element("xpath", f"//input[@id='{field_id}']").get_attribute("value") or "").strip()
            if not _input_already_has_value(current, expected):
                return False
        except NoSuchElementException:
            return False
    return True


def select_authority_document_type(drv, stage="documents"):
    if is_authority_document_type_filled(drv):
        log_info("Тип документа уже выбран, пропуск", stage=stage)
        return True

    if _authority_document_text_fields_filled(drv):
        log_info(
            "Текстовые поля документа уже заполнены — тип не переоткрываем",
            stage=stage,
        )
        return True

    element = WebDriverWait(drv, 10).until(
        EC.presence_of_element_located(("xpath", "//input[@id='userAuthorityConfirmationDocument.documentType']"))
    )
    drv.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", element)
    time.sleep(0.5)
    try:
        element.send_keys(AUTHORITY_DOCUMENT_TYPE)
    except ElementNotInteractableException:
        ActionChains(drv).send_keys(AUTHORITY_DOCUMENT_TYPE).perform()
    time.sleep(0.8)

    try:
        options = _wait_react_select_options(drv, timeout=6)
        for opt in options:
            if AUTHORITY_DOCUMENT_TYPE in (opt.text or ""):
                drv.execute_script("arguments[0].click();", opt)
                log_info("Тип документа выбран кликом", stage=stage)
                time.sleep(0.5)
                return is_authority_document_type_filled(drv)
    except TimeoutException:
        pass

    element.send_keys(Keys.ARROW_DOWN)
    time.sleep(0.5)
    element.send_keys(Keys.ENTER)
    time.sleep(0.5)
    log_info("Тип документа выбран ARROW_DOWN+ENTER", stage=stage)
    return is_authority_document_type_filled(drv)


def is_authority_document_filled(drv):
    return _authority_document_text_fields_filled(drv)


def fill_authority_document_fields(drv, stage="documents"):
    """Документ о полномочиях — заполняет только пустые поля, без дублирования."""
    if is_authority_document_filled(drv):
        log_info("Документ о полномочиях уже заполнен, пропуск", stage=stage)
        return True

    if _authority_document_text_fields_filled(drv):
        log_info(
            "Текстовые поля документа уже заполнены — повторный ввод не нужен",
            stage=stage,
        )
        return True

    select_authority_document_type(drv, stage=stage)
    time.sleep(0.5)

    _set_input_if_needed(drv, "userAuthorityConfirmationDocument.documentNumber", DOCUMENT_NUMBER, stage=stage)
    time.sleep(0.3)
    _set_input_if_needed(drv, "userAuthorityConfirmationDocument.documentIssueDate", DOCUMENT_DATE, stage=stage)
    time.sleep(0.3)
    _set_input_if_needed(drv, "userAuthorityConfirmationDocument.issuingAuthority", ISSUING_AUTHORITY, stage=stage)
    time.sleep(0.3)

    if CORRECTION:
        for xpath in (
            "//textarea[@id='groundsForDataFurnishing']",
            "//textarea[@name='groundsForDataFurnishing']",
        ):
            try:
                textarea = drv.find_element("xpath", xpath)
                current = (textarea.get_attribute("value") or textarea.text or "").strip()
                if _input_already_has_value(current, CORRECTION):
                    log_info("Основание предоставления уже заполнено", stage=stage)
                    break
                if current:
                    textarea.clear()
                textarea.send_keys(CORRECTION)
                log_info("Основание предоставления заполнено", stage=stage)
                break
            except NoSuchElementException:
                continue
        else:
            log_warning("Поле groundsForDataFurnishing не найдено", stage=stage)

    log_info("Поля документа о полномочиях обработаны", stage=stage)
    return True


def is_vipiska_filled(drv):
    for input_id in ("react-select-6-input", "react-select-5-input", "react-select-4-input"):
        display = _react_select_display_text(drv, input_id)
        if VIPISKA_MARKER in display:
            return True
    return _page_has_single_value_marker(drv, VIPISKA_MARKER)


def _find_vipiska_input(drv, timeout=10):
    for input_id in ("react-select-6-input", "react-select-5-input", "react-select-4-input"):
        try:
            el = WebDriverWait(drv, 2).until(
                EC.presence_of_element_located(("xpath", f"//input[@id='{input_id}']"))
            )
            return el
        except TimeoutException:
            continue
    return WebDriverWait(drv, timeout).until(
        EC.presence_of_element_located(("xpath", "//input[@id='react-select-6-input']"))
    )


def fill_vipiska_if_needed(drv, stage="vipiska"):
    if is_vipiska_filled(drv):
        log_info("Тип выписки уже выбран, пропуск", stage=stage)
        return True

    vipiska_input = _find_vipiska_input(drv)
    drv.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", vipiska_input)
    time.sleep(0.5)
    vipiska_input.send_keys(VIPISKA_TEXT)
    log_info("Тип выписки введён", stage=stage)
    time.sleep(1)

    try:
        options = _wait_react_select_options(drv, timeout=8)
        for opt in options:
            if VIPISKA_MARKER in (opt.text or ""):
                drv.execute_script("arguments[0].click();", opt)
                log_info("Тип выписки выбран кликом", stage=stage)
                time.sleep(1)
                if is_vipiska_filled(drv):
                    return True
    except TimeoutException:
        pass

    vipiska_input.send_keys(Keys.ARROW_DOWN)
    time.sleep(0.5)
    vipiska_input.send_keys(Keys.ENTER)
    time.sleep(1)
    log_info("Тип выписки выбран ARROW_DOWN+ENTER", stage=stage)
    if is_vipiska_filled(drv):
        return True
    log_warning("Тип выписки выбран, но single-value не подтвердился — продолжаем", stage=stage)
    return _page_has_single_value_marker(drv, VIPISKA_MARKER)


def is_csv_confirmed_on_form(drv):
    try:
        els = drv.find_elements("xpath", "//div[contains(text(), 'Добавлено объектов из CSV')]")
        return any(e.is_displayed() for e in els)
    except Exception:
        return False


def is_form_ready_for_submit(drv):
    """Все обязательные поля формы заполнены — можно переходить к отправке."""
    return (
        is_applicant_category_filled(drv)
        and is_address_filled_on_form(drv)
        and is_authority_document_filled(drv)
        and is_vipiska_filled(drv)
    )


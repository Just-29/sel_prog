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
from .constants import AUTHORITY_DOCUMENT_TYPE, VIPISKA_MARKER, VIPISKA_TEXT, VIPISKA_TEXT_2
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


_VIPISKA_DROPDOWN_ID = "requestAboutObject.extractDescription.extractDataRequestType1"
_VIPISKA_FALLBACK_INPUT_IDS = (
    "react-select-4-input",
    "react-select-5-input",
    "react-select-6-input",
    "react-select-7-input",
)


def is_vipiska_filled(drv):
    display = _react_select_display_text(drv, _VIPISKA_DROPDOWN_ID)
    if VIPISKA_MARKER in display:
        return True
    for input_id in _VIPISKA_FALLBACK_INPUT_IDS:
        display = _react_select_display_text(drv, input_id)
        if VIPISKA_MARKER in display:
            return True
    return _page_has_single_value_marker(drv, VIPISKA_MARKER)


def _find_vipiska_input(drv, timeout=10):
    """Ищет живой input «Вид выписки» рядом с extractDataRequestType1, не disabled."""

    def _resolve(d):
        try:
            el = d.execute_script(
                """
                const rootId = arguments[0];
                const root = document.getElementById(rootId)
                    || document.querySelector(`[id="${rootId}"]`);
                const containers = [];
                if (root) {
                    containers.push(
                        root.closest('.rros-ui-lib-dropdown-wrapper')
                        || root.closest('.rros-ui-lib-input-wrapper')
                        || root
                    );
                }
                // Подпись «Вид выписки» — запасной якорь, если id контейнера сменился.
                for (const label of document.querySelectorAll('.rros-ui-lib-input-label')) {
                    const text = (label.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (text === 'Вид выписки') {
                        const wrap = label.closest('.rros-ui-lib-dropdown-wrapper')
                            || label.closest('.rros-ui-lib-input-wrapper')
                            || label.parentElement;
                        if (wrap) containers.push(wrap);
                    }
                }
                for (const container of containers) {
                    if (!container) continue;
                    const candidates = Array.from(
                        container.querySelectorAll("input[id^='react-select-'][id$='-input']")
                    );
                    for (const inp of candidates) {
                        if (inp.disabled) continue;
                        const style = window.getComputedStyle(inp);
                        const visible =
                            style.visibility !== 'hidden'
                            && style.display !== 'none'
                            && (inp.offsetWidth || inp.offsetHeight || inp.getClientRects().length);
                        if (visible) return inp;
                    }
                }
                // Последний фолбэк: любой enabled/visible react-select на странице
                // с placeholder «Выберите значение из справочника» рядом с «Вид выписки».
                return null;
                """,
                _VIPISKA_DROPDOWN_ID,
            )
            return el if el else False
        except Exception:
            return False

    try:
        return WebDriverWait(drv, timeout).until(_resolve)
    except TimeoutException:
        pass

    for input_id in _VIPISKA_FALLBACK_INPUT_IDS:
        for el in drv.find_elements("xpath", f"//input[@id='{input_id}']"):
            try:
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                continue
    raise TimeoutException("Поле «Вид выписки» (react-select) не найдено или disabled")


def _send_keys_to_vipiska(drv, vipiska_input, keys):
    try:
        vipiska_input.send_keys(keys)
    except ElementNotInteractableException:
        ActionChains(drv).send_keys(keys).perform()


def fill_vipiska_if_needed(drv, stage="vipiska"):
    if is_vipiska_filled(drv):
        log_info("Тип выписки уже выбран, пропуск", stage=stage)
        return True

    vipiska_input = _find_vipiska_input(drv)
    log_info(
        "Найдено поле «Вид выписки»",
        stage=stage,
        input_id=vipiska_input.get_attribute("id"),
    )
    drv.execute_script(
        "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
        vipiska_input,
    )
    time.sleep(0.5)
    _send_keys_to_vipiska(drv, vipiska_input, VIPISKA_TEXT) 
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

    _send_keys_to_vipiska(drv, vipiska_input, Keys.ARROW_DOWN)
    time.sleep(0.5)
    _send_keys_to_vipiska(drv, vipiska_input, Keys.ENTER)
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


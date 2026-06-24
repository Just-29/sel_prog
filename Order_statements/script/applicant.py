"""Раздел «Сведения о заявителе»."""
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

from .address import close_address_modals, ensure_applicant_residence_address
from .config import DOCUMENT_DATE, EMAIL
from .constants import (
    APPLICANT_CATEGORY_MARKERS,
    APPLICANT_CATEGORY_TEXT,
    REFERENCE_VALIDATION_MARKERS,
)
from .logging_utils import log_info, log_warning

def _react_select_display_text(drv, input_id):
    """Текст выбранного значения react-select: input.value или single-value в контейнере."""
    try:
        return drv.execute_script(
            """
            const input = document.getElementById(arguments[0]);
            if (!input) return '';
            // В некоторых контролах видимый input может быть readOnly и показывать "текст",
            // даже если значение из справочника фактически не выбрано. В этом случае
            // доверяем только single-value внутри контейнера.
            const isReadOnly = !!input.readOnly;
            if (!isReadOnly) {
                const val = (input.value || '').trim();
                if (val) return val;
            }
            const container = input.closest('.rros-ui-lib-dropdown')
                || input.closest('[class*="dropdown"]')
                || input.parentElement;
            if (container) {
                const sv = container.querySelector('[class*="single-value"]');
                if (sv) {
                    const text = (sv.textContent || '').trim();
                    if (text) return text;
                }
            }
            return '';
            """,
            input_id,
        ) or ""
    except Exception:
        return ""


def _find_related_react_select_input(drv, anchor_input_id, timeout=10):
    """
    Находит "живой" input react-select рядом с якорным input (обычно readOnly).
    Возвращает WebElement input с id вида react-select-*-input.
    """

    def _resolve(d):
        try:
            el = d.execute_script(
                """
                const anchor = document.getElementById(arguments[0]);
                if (!anchor) return null;
                const container =
                    anchor.closest('.rros-ui-lib-dropdown')
                    || anchor.closest('[class*="dropdown"]')
                    || anchor.parentElement;
                if (!container) return null;

                const candidates = Array.from(
                    container.querySelectorAll("input[id^='react-select-'][id$='-input']")
                );
                for (const inp of candidates) {
                    const style = window.getComputedStyle(inp);
                    const visible =
                        style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && inp.offsetParent !== null;
                    const enabled = !inp.disabled;
                    if (visible && enabled) return inp;
                }
                return null;
                """,
                anchor_input_id,
            )
            return el if el else False
        except Exception:
            return False

    return WebDriverWait(drv, timeout).until(_resolve)


def _page_has_single_value_marker(drv, marker):
    """Ищет marker в любом single-value на странице (react-select id может меняться)."""
    if not marker:
        return False
    try:
        found = drv.execute_script(
            """
            const marker = arguments[0];
            return Array.from(document.querySelectorAll('[class*="single-value"]'))
                .some(el => (el.textContent || '').includes(marker));
            """,
            marker,
        )
        if found:
            return True
    except Exception:
        pass
    for el in drv.find_elements("xpath", "//div[contains(@class, 'single-value')]"):
        if marker in (el.text or ""):
            return True
    return False


def _applicant_org_block_visible(drv):
    """Блок организации появляется только после выбора категории из справочника."""
    try:
        org = drv.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].fullname']")
        return bool((org.get_attribute("value") or "").strip())
    except NoSuchElementException:
        return False


def _applicant_category_display_text(drv):
    text = _react_select_display_text(drv, "applicantCategory")
    if text:
        return text
    return ""


def _page_has_reference_validation_error(drv):
    """Ошибки справочника только в блоке категории заявителя (не по всей странице)."""
    for marker in REFERENCE_VALIDATION_MARKERS:
        for el in drv.find_elements(
            "xpath",
            "//input[@id='applicantCategory']/ancestor::div[contains(@class, 'form') or contains(@class, 'widget') or contains(@class, 'dropdown')][1]"
            f"//*[contains(text(), '{marker}')]",
        ):
            if el.is_displayed():
                return True
    return False


def _get_applicant_category_input_value(drv):
    try:
        return (
            drv.find_element("xpath", "//input[@id='applicantCategory']").get_attribute("value") or ""
        ).strip()
    except NoSuchElementException:
        return ""


def _applicant_category_field_has_value(drv):
    """Текст категории виден в самом поле (не по блоку организации с сертификата)."""
    display = _applicant_category_display_text(drv)
    input_value = _get_applicant_category_input_value(drv)
    for text in (display, input_value):
        if text and (
            any(m in text for m in APPLICANT_CATEGORY_MARKERS) or len(text) > 15
        ):
            return not _page_has_reference_validation_error(drv)
    return False


def _verify_applicant_category_selected(drv, stage="applicant_category", log_result=True):
    """Проверяет, выбрана ли категория после ввода и ARROW_DOWN+ENTER."""
    display = _applicant_category_display_text(drv)
    input_value = _get_applicant_category_input_value(drv)
    org_visible = _applicant_org_block_visible(drv)

    if log_result:
        log_info(
            "Проверка выбора категории",
            stage=stage,
            single_value=display[:120] if display else "(пусто)",
            input_value=input_value[:120] if input_value else "(пусто)",
            org_block=org_visible,
        )

    # Самый надёжный индикатор — появление блока организации (он появляется только после выбора).
    if org_visible and not _page_has_reference_validation_error(drv):
        if log_result:
            log_info("Категория подтверждена по блоку организации", stage=stage)
        return True

    # Второй по надёжности — single-value react-select (display).
    if display and (
        any(m in display for m in APPLICANT_CATEGORY_MARKERS) or len(display) > 15
    ):
        if not _page_has_reference_validation_error(drv):
            if log_result:
                log_info("Категория подтверждена по single-value", stage=stage, value=display[:120])
            return True

    # Фолбэк: текст в readOnly поле может быть обманчивым, но оставляем как последний шанс
    # для старого UI, где value действительно отражал выбор.
    if input_value and (
        any(m in input_value for m in APPLICANT_CATEGORY_MARKERS) or len(input_value) > 15
    ):
        if not _page_has_reference_validation_error(drv):
            if log_result:
                log_info("Категория подтверждена по значению input", stage=stage, value=input_value[:120])
            return True

    if log_result:
        log_warning("Категория не выбрана — значение в поле не найдено", stage=stage, driver=drv)
    return False


def is_applicant_category_filled(drv):
    return _verify_applicant_category_selected(
        drv, stage="applicant_category_check", log_result=False,
    )


def _type_applicant_category_text(drv, category_input, stage="applicant_category"):
    try:
        category_input.send_keys(APPLICANT_CATEGORY_TEXT)
    except ElementNotInteractableException:
        drv.execute_script("arguments[0].click();", category_input)
        time.sleep(0.3)
        category_input.send_keys(APPLICANT_CATEGORY_TEXT)
    log_info("Текст категории заявителя введён", stage=stage)


def _confirm_applicant_category_keys(drv, category_input, stage="applicant_category"):
    try:
        category_input.send_keys(Keys.ARROW_DOWN)
    except ElementNotInteractableException:
        ActionChains(drv).send_keys(Keys.ARROW_DOWN).perform()
    log_info("Стрелка вниз отправлена", stage=stage)
    time.sleep(1)

    try:
        category_input.send_keys(Keys.ENTER)
    except ElementNotInteractableException:
        ActionChains(drv).send_keys(Keys.ENTER).perform()
    log_info("Enter отправлен", stage=stage)
    time.sleep(1)


def confirm_applicant_category_with_keys(drv, stage="applicant_category"):
    """Подтверждает категорию — ARROW_DOWN + ENTER, как в Qwartal.py."""
    if _applicant_category_field_has_value(drv):
        log_info("Категория уже в поле", stage=stage)
        return True

    category_input = WebDriverWait(drv, 10).until(
        EC.presence_of_element_located(("xpath", "//input[@id='applicantCategory']"))
    )
    drv.execute_script("arguments[0].scrollIntoView({block: 'center'});", category_input)
    time.sleep(0.3)
    _confirm_applicant_category_keys(drv, category_input, stage=stage)
    return _verify_applicant_category_selected(drv, stage=stage)


def select_applicant_category(drv, stage="applicant_category"):
    """Выбор категории: ввод текста → ARROW_DOWN → ENTER → проверка (как Qwartal.py)."""
    close_address_modals(drv, stage=stage)

    if _applicant_category_field_has_value(drv):
        log_info("Категория уже в поле, повторный ввод не нужен", stage=stage)
        return True

    category_anchor = WebDriverWait(drv, 15).until(
        EC.presence_of_element_located(("xpath", "//input[@id='applicantCategory']"))
    )
    drv.execute_script("arguments[0].scrollIntoView({block: 'center'});", category_anchor)
    time.sleep(0.3)

    # В новом UI `#applicantCategory` часто readOnly: он только открывает справочник.
    # Реальный ввод идёт в соседний `react-select-*-input`.
    try:
        drv.execute_script("arguments[0].click();", category_anchor)
        log_info("Открыт справочник категории заявителя", stage=stage)
    except Exception:
        pass
    time.sleep(0.4)

    try:
        category_input = _find_related_react_select_input(drv, "applicantCategory", timeout=10)
        drv.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", category_input)
        time.sleep(0.2)
    except Exception:
        # Фолбэк на старый вариант (если связанным input не оказался react-select)
        category_input = category_anchor

    # Вводим текст и стараемся выбрать опцию кликом (надёжнее, чем ARROW_DOWN/ENTER).
    try:
        category_input.send_keys(APPLICANT_CATEGORY_TEXT)
    except ElementNotInteractableException:
        ActionChains(drv).send_keys(APPLICANT_CATEGORY_TEXT).perform()
    log_info("Текст категории заявителя введён", stage=stage)
    time.sleep(0.8)

    try:
        options = _wait_react_select_options(drv, timeout=10)
        for opt in options:
            txt = (opt.text or "").strip()
            if not txt:
                continue
            if any(m in txt for m in APPLICANT_CATEGORY_MARKERS) or APPLICANT_CATEGORY_TEXT in txt:
                drv.execute_script("arguments[0].click();", opt)
                log_info("Категория заявителя выбрана кликом", stage=stage, option=txt[:120])
                time.sleep(0.8)
                return _verify_applicant_category_selected(drv, stage=stage)
    except TimeoutException:
        pass

    # Фолбэк: клавиши (на случай, если список не удалось прочитать по DOM)
    _confirm_applicant_category_keys(drv, category_input, stage=stage)
    return _verify_applicant_category_selected(drv, stage=stage)


def _wait_react_select_options(drv, timeout=10):
    def options_ready(d):
        opts = [
            o for o in d.find_elements(
                "xpath", "//div[contains(@id, 'react-select') and contains(@id, '-option-')]"
            )
            if o.is_displayed() and (o.text or "").strip()
        ]
        return opts if opts else False

    return WebDriverWait(drv, timeout).until(options_ready)


def fill_applicant_form_fields(drv, stage="form_fields"):
    """Дата регистрации и email-поля раздела заявителя."""
    try:
        reg_date = drv.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].regDate']")
        if not (reg_date.get_attribute("value") or "").strip():
            reg_date.clear()
            reg_date.send_keys(DOCUMENT_DATE)
            log_info("Введена дата документа", stage=stage, date=DOCUMENT_DATE)
    except NoSuchElementException:
        pass

    for email_id in (
        "rorganizationOrGovernmentArray[0].email",
        "fullNameDocumentAndAdditionalInformationArray[0].email",
        "requestAboutObject.deliveryActionEmail",
    ):
        try:
            el = drv.find_element("xpath", f"//input[@id='{email_id}']")
            current = (el.get_attribute("value") or "").strip()
            if current != EMAIL:
                el.clear()
                el.send_keys(EMAIL)
        except NoSuchElementException:
            pass
    log_info("Email-поля заполнены", stage=stage, email=EMAIL)
    ensure_applicant_residence_address(drv, stage="applicant_address")


def ensure_applicant_section_complete(drv, stage="applicant_category"):
    """Раздел «Сведения о заявителе» — ввод текста, ARROW_DOWN+ENTER, проверка."""
    close_address_modals(drv, stage=stage)

    if _applicant_category_field_has_value(drv):
        log_info("Категория заявителя уже в поле", stage=stage)
        fill_applicant_form_fields(drv)
        return True

    log_info("Категория пустая — ввод и выбор из справочника", stage=stage)
    try:
        if not select_applicant_category(drv, stage=stage):
            log_warning("Не удалось выбрать категорию заявителя", stage=stage, driver=drv)
            return False
    except Exception as e:
        log_warning("Ошибка при выборе категории заявителя", stage=stage, exc=e, driver=drv)
        return False

    fill_applicant_form_fields(drv)
    if not ensure_applicant_residence_address(drv, stage="applicant_address"):
        log_warning("Адрес места жительства заявителя не заполнен", stage=stage, driver=drv)
        return False
    time.sleep(0.5)

    ok = _verify_applicant_category_selected(drv, stage=stage)
    if ok:
        log_info("Раздел заявителя заполнен", stage=stage)
    return ok


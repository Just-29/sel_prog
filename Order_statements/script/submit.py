
"""Отправка заявки: Далее, сертификат, финализация."""
import time

from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .constants import (
    CERTIFICATE_OPTION_XPATH,
    MAX_SUBMIT_ERROR_RETRIES,
    SUBMIT_PROCESSING_MARKERS,
    SUBMIT_REQUEST_ERROR_MARKERS,
    SUBMIT_RESULT_TIMEOUT,
    SUBMIT_POLL_INTERVAL,
    SUBMIT_SUCCESS_XPATH,
)
from .applicant import (
    _page_has_reference_validation_error,
    confirm_applicant_category_with_keys,
    fill_applicant_form_fields,
    is_applicant_category_filled,
    select_applicant_category,
)
from .address import (
    _applicant_residence_modal_visible,
    _page_has_required_field_error,
    ensure_applicant_residence_address,
)
from .logging_utils import log_info, log_warning
from .native_dialogs import pulse_cryptopro_access, pulse_gosplugin_dialogs, pulse_native_dialogs
from .csv_upload import remove_csv_from_interface
from .session import close_modal_window

def _page_has_submit_request_error(drv):
    """Ошибка отправки/финализации заявления (500, 502 и т.п.)."""
    try:
        for xpath in (
            "//div[contains(@class, 'rros-ui-lib-errors')]",
            "//div[contains(@class, 'rros-ui-lib-error')]",
            "//div[contains(@class, 'rros-ui-lib-error-content')]",
        ):
            for el in drv.find_elements("xpath", xpath):
                if not el.is_displayed():
                    continue
                text = (el.text or "").strip()
                if text and any(marker in text for marker in SUBMIT_REQUEST_ERROR_MARKERS):
                    return True
        for el in drv.find_elements("xpath", "//div[contains(@class, 'rros-ui-lib-error-message')]"):
            if not el.is_displayed():
                continue
            text = el.text or ""
            if any(
                marker in text
                for marker in (
                    "Не удалось отправить заявление",
                    "Не удалось финализировать заявление",
                )
            ):
                return True
    except Exception:
        pass
    return False


def _dismiss_submit_request_error(drv, stage="submit"):
    """Закрывает всплывающее окно ошибки отправки/финализации."""
    try:
        containers = drv.find_elements(
            "xpath",
            "//div[contains(@class, 'rros-ui-lib-errors')]"
            " | //div[contains(@class, 'rros-ui-lib-error')]",
        )
        for block in containers:
            if not block.is_displayed():
                continue
            text = (block.text or "").strip()
            if text and not any(marker in text for marker in SUBMIT_REQUEST_ERROR_MARKERS):
                continue
            for xpath in (
                ".//button[contains(@class, 'rros-ui-lib-error-close')]",
                ".//button[contains(@class, 'rros-ui-lib-button--link')]",
            ):
                btns = block.find_elements("xpath", xpath)
                if btns:
                    drv.execute_script("arguments[0].click();", btns[0])
                    log_info("Окно ошибки отправки закрыто", stage=stage)
                    time.sleep(1)
                    return True
    except Exception:
        pass
    return False


def _is_submit_success_visible(drv):
    try:
        return any(
            el.is_displayed()
            for el in drv.find_elements("xpath", SUBMIT_SUCCESS_XPATH)
        )
    except Exception:
        return False


def _is_submit_processing(drv):
    """Сервер обрабатывает отправку заявки (модалка «Идет процесс отправки документов»)."""
    try:
        for el in drv.find_elements(
            "xpath",
            "//div[contains(@class, 'rros-ui-lib-modal__window')]"
            " | //div[contains(@class, 'modal')]"
            " | //*[contains(@class, 'alert')]",
        ):
            if not el.is_displayed():
                continue
            text = (el.text or "").strip()
            if text and any(marker in text for marker in SUBMIT_PROCESSING_MARKERS):
                return True
    except Exception:
        pass
    return False


def _is_certificate_selector_visible(drv):
    try:
        return any(
            el.is_displayed()
            for el in drv.find_elements("xpath", CERTIFICATE_OPTION_XPATH)
        )
    except Exception:
        return False


def _wait_submit_result(drv, stage="submit", timeout=SUBMIT_RESULT_TIMEOUT):
    """
    Ждёт успешной отправки или ошибки сервера (до timeout сек).
    Возвращает 'success', 'error' или 'timeout'.
    """
    deadline = time.time() + timeout
    started = time.time()
    last_log = 0.0
    while time.time() < deadline:
        if _is_submit_success_visible(drv):
            return "success"
        if _page_has_submit_request_error(drv):
            return "error"
        if time.time() - last_log >= SUBMIT_POLL_INTERVAL:
            elapsed = int(time.time() - started)
            if _is_submit_processing(drv):
                log_info(
                    f"Сервер обрабатывает отправку заявки ({elapsed}/{timeout} сек)",
                    stage=stage,
                )
            else:
                log_info(
                    f"Ожидание результата отправки заявки ({elapsed}/{timeout} сек)",
                    stage=stage,
                )
            last_log = time.time()
        time.sleep(2)
    return "timeout"


def _wait_for_certificate_or_submit_outcome(drv, stage="submit", timeout=SUBMIT_RESULT_TIMEOUT):
    """
    Ждёт появления выбора сертификата, успешной отправки или ошибки.
    Возвращает 'certificate', 'success', 'error' или 'timeout'.
    """
    deadline = time.time() + timeout
    started = time.time()
    last_log = 0.0
    while time.time() < deadline:
        if _is_submit_success_visible(drv):
            return "success"
        if _page_has_submit_request_error(drv):
            return "error"
        if _is_certificate_selector_visible(drv):
            return "certificate"
        if time.time() - last_log >= SUBMIT_POLL_INTERVAL:
            elapsed = int(time.time() - started)
            if _is_submit_processing(drv):
                log_info(
                    f"Сервер обрабатывает отправку документов ({elapsed}/{timeout} сек)",
                    stage=stage,
                )
            else:
                log_info(
                    f"Ожидание сертификата или результата отправки ({elapsed}/{timeout} сек)",
                    stage=stage,
                )
            last_log = time.time()
        time.sleep(2)
    return "timeout"


def _click_dalee_button(drv, step_name, stage="submit", timeout=15):
    btn = WebDriverWait(drv, timeout).until(
        EC.element_to_be_clickable(("xpath", "//button[text()='Далее']"))
    )
    drv.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", btn)
    log_info(f"Кнопка 'Далее' нажата ({step_name})", stage=stage)
    time.sleep(3)


def _handle_dalee_validation_errors(drv, step_name, stage="submit"):
    """Исправляет ошибки валидации после «Далее». Возвращает True, если форма в порядке."""
    if _page_has_reference_validation_error(drv):
        log_warning(
            f"После «Далее» ({step_name}) — ошибка валидации справочника",
            stage=stage, driver=drv,
        )
        if not is_applicant_category_filled(drv):
            select_applicant_category(drv, stage="applicant_category")
        else:
            confirm_applicant_category_with_keys(drv, stage="applicant_category")
        fill_applicant_form_fields(drv, stage="form_fields")
        ensure_applicant_residence_address(drv, stage="applicant_address")
        time.sleep(0.5)
        btn = WebDriverWait(drv, 10).until(
            EC.element_to_be_clickable(("xpath", "//button[text()='Далее']"))
        )
        drv.execute_script("arguments[0].click();", btn)
        log_info(f"Повторное нажатие «Далее» ({step_name})", stage=stage)
        time.sleep(3)
        return not _page_has_reference_validation_error(drv)

    if _page_has_required_field_error(drv) or _applicant_residence_modal_visible(drv):
        log_warning(
            f"После «Далее» ({step_name}) — незаполнен адрес заявителя",
            stage=stage, driver=drv,
        )
        if ensure_applicant_residence_address(drv, stage="applicant_address"):
            btn = WebDriverWait(drv, 10).until(
                EC.element_to_be_clickable(("xpath", "//button[text()='Далее']"))
            )
            drv.execute_script("arguments[0].click();", btn)
            log_info(f"Повторное нажатие «Далее» после адреса заявителя ({step_name})", stage=stage)
            time.sleep(3)
            return not (
                _page_has_required_field_error(drv)
                or _applicant_residence_modal_visible(drv)
            )
        return False

    return True


def restart_form_with_same_csv(drv, upload_file, file_ctx, stage="submit"):
    """Сброс формы для повторного заполнения с тем же CSV."""
    log_info(
        "Перезапуск заполнения формы с тем же CSV",
        stage=stage, file=upload_file.name,
    )
    _dismiss_submit_request_error(drv, stage=stage)
    close_modal_window(drv)
    remove_csv_from_interface(drv, upload_file.name)
    file_ctx["page_loaded"] = False


def click_dalee_and_verify(drv, step_name, stage="submit", timeout=15):
    """
    Нажимает «Далее», проверяет валидацию и ошибки отправки (500).
    Возвращает True при успехе, False при ошибке валидации, 'restart' если
    ошибка отправки повторилась более MAX_SUBMIT_ERROR_RETRIES раз.
    """
    submit_error_count = 0

    while True:
        _click_dalee_button(drv, step_name, stage=stage, timeout=timeout)

        if not _handle_dalee_validation_errors(drv, step_name, stage=stage):
            return False

        if not _page_has_submit_request_error(drv):
            return True

        submit_error_count += 1
        log_warning(
            f"После «Далее» ({step_name}) — ошибка отправки заявления "
            f"({submit_error_count}/{MAX_SUBMIT_ERROR_RETRIES})",
            stage=stage, driver=drv,
        )

        if submit_error_count > MAX_SUBMIT_ERROR_RETRIES:
            log_warning(
                f"Ошибка отправки повторилась более {MAX_SUBMIT_ERROR_RETRIES} раз "
                f"— перезапуск заполнения с тем же CSV",
                stage=stage, driver=drv,
            )
            return "restart"

        _dismiss_submit_request_error(drv, stage=stage)
        time.sleep(1)


def _select_certificate(drv, stage="submit", timeout=15):
    opt = WebDriverWait(drv, timeout).until(
        EC.visibility_of_element_located(("xpath", CERTIFICATE_OPTION_XPATH))
    )
    drv.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", opt)
    log_info("Сертификат выбран", stage=stage)
    pulse_gosplugin_dialogs()
    pulse_cryptopro_access()
    pulse_native_dialogs()
    time.sleep(1)


def _click_vybrat_button(drv, stage="submit", timeout=15):
    btn = WebDriverWait(drv, timeout).until(
        EC.element_to_be_clickable(("xpath", "//button[text()='Выбрать']"))
    )
    drv.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", btn)
    log_info("Кнопка 'Выбрать' нажата, заявка отправляется", stage=stage)
    pulse_gosplugin_dialogs(30)
    pulse_cryptopro_access(30)
    pulse_native_dialogs(15)


def finalize_application_with_certificate(
    drv, stage="submit", timeout=15, result_timeout=SUBMIT_RESULT_TIMEOUT,
):
    """
    Ждёт окончания обработки сервером, выбирает сертификат, нажимает «Выбрать»,
    ждёт подтверждение или ошибку (до result_timeout сек).
    Возвращает True при успехе, False при таймауте, 'restart' если ошибка
    повторилась более MAX_SUBMIT_ERROR_RETRIES раз.
    """
    submit_error_count = 0

    while True:
        pre_result = _wait_for_certificate_or_submit_outcome(
            drv, stage=stage, timeout=result_timeout,
        )
        if pre_result == "success":
            return True
        if pre_result == "timeout":
            log_warning(
                f"Таймаут ожидания сертификата или результата отправки ({result_timeout} сек)",
                stage=stage, driver=drv,
            )
            return False
        if pre_result == "error":
            submit_error_count += 1
            log_warning(
                f"Ошибка отправки заявления ({submit_error_count}/{MAX_SUBMIT_ERROR_RETRIES})",
                stage=stage, driver=drv,
            )
            if submit_error_count > MAX_SUBMIT_ERROR_RETRIES:
                log_warning(
                    f"Ошибка отправки повторилась более {MAX_SUBMIT_ERROR_RETRIES} раз "
                    f"— перезапуск заполнения с тем же CSV",
                    stage=stage, driver=drv,
                )
                return "restart"
            _dismiss_submit_request_error(drv, stage=stage)
            time.sleep(1)
            continue

        _select_certificate(drv, stage=stage, timeout=timeout)
        _click_vybrat_button(drv, stage=stage, timeout=timeout)

        submit_result = _wait_submit_result(drv, stage=stage, timeout=result_timeout)
        if submit_result == "success":
            return True
        if submit_result == "timeout":
            log_warning(
                f"Таймаут ожидания подтверждения отправки ({result_timeout} сек)",
                stage=stage, driver=drv,
            )
            return False

        submit_error_count += 1
        log_warning(
            f"После «Выбрать» — ошибка финализации заявления "
            f"({submit_error_count}/{MAX_SUBMIT_ERROR_RETRIES})",
            stage=stage, driver=drv,
        )

        if submit_error_count > MAX_SUBMIT_ERROR_RETRIES:
            log_warning(
                f"Ошибка финализации повторилась более {MAX_SUBMIT_ERROR_RETRIES} раз "
                f"— перезапуск заполнения с тем же CSV",
                stage=stage, driver=drv,
            )
            return "restart"

        _dismiss_submit_request_error(drv, stage=stage)
        time.sleep(1)


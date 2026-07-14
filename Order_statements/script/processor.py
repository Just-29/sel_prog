"""Основной цикл обработки CSV-файлов."""
import time

from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .address import (
    close_address_modals,
    is_address_filled_on_form,
    select_address_ultimate,
)
from .applicant import (
    ensure_applicant_section_complete,
    fill_applicant_form_fields,
    is_applicant_category_filled,
)
from .config import PDF_FILE_NAME, SIGNATURE_FILE_NAME, UPLOADS_CSV_DIR, UPLOADS_DIR
from .constants import MAX_FILE_ATTEMPTS, VIPISKA_MARKER
from .csv_upload import (
    CSV_RESULT_SESSION_EXPIRED,
    CSV_RESULT_SUCCESS,
    remove_csv_from_interface,
    wait_for_file_upload_by_title,
)
from .documents import (
    _page_has_single_value_marker,
    fill_authority_document_fields,
    fill_vipiska_if_needed,
    is_authority_document_filled,
    is_csv_confirmed_on_form,
    is_form_ready_for_submit,
    is_vipiska_filled,
)
from .logging_utils import log_error, log_info, log_warning, save_selenium_note
from .login import login_funct
from .session import (
    close_modal_window,
    delete_local_csv_file,
    ensure_form_page_ready,
    record_file_send_failure,
    recover_session_if_expired,
)
from .submit import (
    click_dalee_and_verify,
    finalize_application_with_certificate,
    restart_form_with_same_csv,
)
from .upload_queue import list_csv_files

def run_processing_loop(driver, wait):
    pdf_path = UPLOADS_DIR / PDF_FILE_NAME
    signature_path = UPLOADS_DIR / SIGNATURE_FILE_NAME
    for upload_file in list_csv_files(UPLOADS_CSV_DIR):
        flag_download_CSV_file = False
        file_ctx = {"page_loaded": False}
        file_attempt = 0

        while flag_download_CSV_file == False:
            file_attempt += 1
            if file_attempt > MAX_FILE_ATTEMPTS:
                if upload_file.is_file() and upload_file.suffix.lower() == ".csv":
                    record_file_send_failure(
                        driver, upload_file, MAX_FILE_ATTEMPTS,
                        f"превышен лимит попыток ({MAX_FILE_ATTEMPTS})",
                    )
                else:
                    log_error(
                        f"Превышен лимит попыток ({MAX_FILE_ATTEMPTS}), файл пропущен",
                        stage="main_loop",
                        file=upload_file.name if upload_file.is_file() else str(upload_file),
                    )
                break

            if upload_file.is_file() and upload_file.suffix.lower() == '.csv':
                stage = "main_loop"

                def on_file_failure(reason, exc=None, failure_stage="main_loop"):
                    record_file_send_failure(
                        driver, upload_file, file_attempt, reason, exc=exc, stage=failure_stage,
                    )
                    file_ctx["page_loaded"] = False
                    close_modal_window(driver)
                log_info(
                    f"Начало обработки файла: {upload_file.name} (попытка {file_attempt}/{MAX_FILE_ATTEMPTS})",
                    stage=stage, file=upload_file.name,
                )

                if recover_session_if_expired(driver, stage=stage):
                    file_ctx["page_loaded"] = False
                    continue

                if not ensure_form_page_ready(driver, stage="applicant_category", file_ctx=file_ctx):
                    on_file_failure("страница формы не готова к заполнению", failure_stage="applicant_category")
                    continue

                form_ready = is_form_ready_for_submit(driver)
                if form_ready:
                    log_info(
                        "Форма уже полностью заполнена — повторный ввод полей пропущен",
                        stage=stage, file=upload_file.name,
                    )
                elif is_address_filled_on_form(driver):
                    log_info(
                        "Адрес объекта уже заполнен — пропуск ввода адреса",
                        stage="main_loop", file=upload_file.name,
                    )
                    if not ensure_applicant_section_complete(driver, stage="applicant_category"):
                        on_file_failure("раздел «Сведения о заявителе» не заполнен", failure_stage="applicant_category")
                        continue
                else:
                    if not ensure_applicant_section_complete(driver, stage="applicant_category"):
                        if not is_applicant_category_filled(driver):
                            on_file_failure(
                                "раздел «Сведения о заявителе» не заполнен или не прошёл валидацию",
                                failure_stage="applicant_category",
                            )
                            continue

                    time.sleep(1)

                    try:
                        if is_address_filled_on_form(driver):
                            log_info(
                                "Адрес уже заполнен, пропускаем ввод",
                                stage="address", file=upload_file.name,
                            )
                        else:
                            if select_address_ultimate(driver):
                                log_info("Адрес успешно выбран", stage="address", file=upload_file.name)
                            elif is_address_filled_on_form(driver):
                                log_info(
                                    "Адрес заполнен (определено после попыток)",
                                    stage="address", file=upload_file.name,
                                )
                            else:
                                close_address_modals(driver, stage="address")
                                if is_form_ready_for_submit(driver):
                                    log_warning(
                                        "Ошибка адреса, но остальная форма заполнена — продолжаем",
                                        stage="address", file=upload_file.name,
                                    )
                                else:
                                    on_file_failure("критическая ошибка с адресом", failure_stage="address")
                                    continue

                        try:
                            WebDriverWait(driver, 10).until(
                                EC.element_to_be_clickable(("xpath", "//body"))
                            )
                            driver.execute_script("arguments[0].click();", driver.find_element("xpath", "//body"))
                            log_info("Форма доступна для взаимодействия", stage="address")
                        except Exception as e:
                            log_warning(
                                "Форма всё ещё заблокирована после выбора адреса",
                                stage="address", exc=e, driver=driver, file=upload_file.name,
                            )

                    except Exception as e:
                        if is_address_filled_on_form(driver) or is_form_ready_for_submit(driver):
                            log_warning(
                                "Ошибка адреса, но форма заполнена — продолжаем",
                                stage="address", exc=e, file=upload_file.name,
                            )
                        else:
                            on_file_failure(
                                "ошибка при открытии модального окна адреса",
                                exc=e, failure_stage="address",
                            )
                            continue

                    time.sleep(2)

                try:
                    fill_authority_document_fields(driver, stage="documents")
                except Exception as e:
                    if is_authority_document_filled(driver) or is_form_ready_for_submit(driver):
                        log_warning(
                            "Ошибка документов, но поля заполнены — продолжаем",
                            stage="documents", exc=e, file=upload_file.name,
                        )
                    else:
                        on_file_failure(
                            "ошибка при заполнении полей документа",
                            exc=e, failure_stage="documents",
                        )
                        continue

                time.sleep(1)

                try:
                    if not fill_vipiska_if_needed(driver, stage="vipiska"):
                        log_warning(
                            "Тип выписки не подтверждён проверкой, но продолжаем",
                            stage="vipiska", file=upload_file.name,
                        )
                except Exception as e:
                    if is_vipiska_filled(driver) or _page_has_single_value_marker(driver, VIPISKA_MARKER):
                        log_warning(
                            "Ошибка выписки, но тип уже выбран — продолжаем",
                            stage="vipiska", exc=e, file=upload_file.name,
                        )
                    else:
                        on_file_failure(
                            "ошибка при выборе типа выписки",
                            exc=e, failure_stage="vipiska",
                        )
                        continue

                if not is_csv_confirmed_on_form(driver):
                    try:
                        driver.find_element("xpath", "(//input[@type='file'])[1]").send_keys(str(pdf_path))
                        time.sleep(5)
                        log_info(f"Загружен PDF: {PDF_FILE_NAME}", stage="file_upload")

                        driver.find_element("tag name", "body").click()
                        time.sleep(1)

                        driver.find_element("xpath", "(//input[@type='file'])[2]").send_keys(str(signature_path))
                        time.sleep(5)
                        log_info(f"Загружена подпись: {SIGNATURE_FILE_NAME}", stage="file_upload")
                    except Exception as e:
                        if is_csv_confirmed_on_form(driver):
                            log_warning("Ошибка загрузки файлов, но CSV уже на форме", stage="file_upload", exc=e)
                        else:
                            on_file_failure(
                                "ошибка при загрузке PDF/подписи",
                                exc=e, failure_stage="file_upload",
                            )
                            continue

                    csv_upload_done = False
                    session_needs_refresh = False
                    attempt = 0
                    max_attempts = 5

                    while not csv_upload_done and attempt < max_attempts and not session_needs_refresh:
                        attempt += 1
                        log_info(f"Попытка загрузки CSV {attempt}/{max_attempts}", stage="csv_upload", file=upload_file.name)

                        result = wait_for_file_upload_by_title(driver, upload_file)

                        if result == CSV_RESULT_SUCCESS:
                            csv_upload_done = True
                        elif result == CSV_RESULT_SESSION_EXPIRED:
                            remove_csv_from_interface(driver, upload_file.name)
                            file_ctx["page_loaded"] = False
                            login_funct(driver)
                            session_needs_refresh = True
                        else:
                            log_warning(
                                "CSV не загружен, очистка и повтор",
                                stage="csv_upload", file=upload_file.name, attempt=attempt,
                            )
                            remove_csv_from_interface(driver, upload_file.name)
                            if attempt < max_attempts:
                                log_info("Повторная попытка CSV через 3 сек", stage="csv_upload", attempt=attempt)
                                time.sleep(3)

                    if session_needs_refresh:
                        continue

                    if not csv_upload_done:
                        on_file_failure("CSV не загружен после всех попыток", failure_stage="csv_upload")
                        continue
                else:
                    log_info("CSV уже на форме, повторная загрузка пропущена", stage="csv_upload", file=upload_file.name)

                try:
                    wait.until(EC.presence_of_element_located(("xpath", "//div[text()='Добавлено объектов из CSV-файла:']")))
                    log_info("CSV-файл подтверждён на странице", stage="csv_upload", file=upload_file.name)
                except Exception as e:
                    if recover_session_if_expired(driver, stage="csv_upload"):
                        file_ctx["page_loaded"] = False
                        continue
                    on_file_failure(
                        "текст «Добавлено объектов из CSV-файла» не появился на форме",
                        exc=e, failure_stage="csv_upload",
                    )
                    continue

                time.sleep(2)

                if recover_session_if_expired(driver, stage="submit"):
                    file_ctx["page_loaded"] = False
                    continue

                if not is_applicant_category_filled(driver):
                    if not ensure_applicant_section_complete(driver, stage="applicant_category"):
                        on_file_failure(
                            "раздел «Сведения о заявителе» не заполнен перед отправкой",
                            failure_stage="applicant_category",
                        )
                        continue
                else:
                    fill_applicant_form_fields(driver)

                try:
                    dalee_result = click_dalee_and_verify(driver, "шаг 1")
                    if dalee_result == "restart":
                        restart_form_with_same_csv(driver, upload_file, file_ctx)
                        continue
                    if not dalee_result:
                        on_file_failure(
                            "после первой «Далее» осталась ошибка валидации заявителя",
                            failure_stage="submit",
                        )
                        continue

                    time.sleep(2)
                    dalee_result = click_dalee_and_verify(driver, "шаг 2")
                    if dalee_result == "restart":
                        restart_form_with_same_csv(driver, upload_file, file_ctx)
                        continue
                    if not dalee_result:
                        on_file_failure(
                            "после второй «Далее» осталась ошибка валидации заявителя",
                            failure_stage="submit",
                        )
                        continue

                    finalize_result = finalize_application_with_certificate(driver)
                    if finalize_result == "restart":
                        restart_form_with_same_csv(driver, upload_file, file_ctx)
                        continue
                    if not finalize_result:
                        on_file_failure(
                            "заявка не подтверждена — сообщение об отправке не появилось",
                            failure_stage="result",
                        )
                        continue
                except Exception as e:
                    if recover_session_if_expired(driver, stage="submit"):
                        file_ctx["page_loaded"] = False
                        continue
                    on_file_failure(
                        "ошибка на этапе отправки заявки (кнопки Далее/Выбрать)",
                        exc=e, failure_stage="submit",
                    )
                    continue

                try:
                    save_selenium_note(driver, f"УСПЕХ: Файл {upload_file} отправлен")
                    log_info(f"Заявка успешно отправлена: {upload_file.name}", stage="result", file=upload_file.name)
                    delete_local_csv_file(upload_file)
                    flag_download_CSV_file = True
                    time.sleep(10)
                except Exception as e:
                    on_file_failure(
                        "ошибка при сохранении результата отправки",
                        exc=e, failure_stage="result",
                    )
                    continue
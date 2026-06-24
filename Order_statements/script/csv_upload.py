"""Загрузка CSV на форму Росреестра."""
import time

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .constants import (
    CSV_APPLY_BUTTON_XPATH,
    CSV_FILE_INPUT_XPATH,
    CSV_MODAL_GRACE_WHILE_LOADING,
    CSV_MODAL_TIMEOUT,
    CSV_POLL_INTERVAL,
    CSV_RESULT_RETRY,
    CSV_RESULT_SESSION_EXPIRED,
    CSV_RESULT_SUCCESS,
    CSV_UPLOAD_BUTTON_XPATHS,
    CSV_UPLOAD_DELETE_XPATHS,
    CSV_UPLOAD_ERROR_XPATHS,
    CSV_UPLOAD_ITEM_XPATHS,
)
from .address import close_address_modals
from .logging_utils import log_exception, log_info, log_scenario, log_warning
from .session import close_modal_window, is_session_expired

def collect_csv_upload_state(driver, file_path=None):
  """Снимок состояния блока загрузки CSV — для диагностики сценария «файл есть, объекты не добавлены»."""
  state = {}
  fname = file_path.name if file_path is not None else None

  try:
    warn_els = driver.find_elements("xpath", "//div[contains(@class, 'csv-control__count-warn')]")
    state["csv_warning"] = next(
      ((el.text or "").strip() for el in warn_els if (el.text or "").strip()),
      None,
    )

    count_els = driver.find_elements("xpath", "//div[contains(@class, 'csv-control__count')]")
    state["csv_status_messages"] = [
      (el.text or "").strip()[:300]
      for el in count_els
      if (el.text or "").strip()
    ]

    if fname:
      xpath = (
        f"//span[contains(@title, '{fname}') "
        f"and contains(@class, 'rros-ui-lib-file-upload__item__name')]"
      )
      items = driver.find_elements("xpath", xpath)
      state["file_in_upload_list"] = len(items) > 0

    modal_titles = driver.find_elements("xpath", "//h3[contains(@class, 'my-objects-modal')]")
    state["modal_title"] = (modal_titles[0].text or "").strip()[:200] if modal_titles else None

    max_count_els = driver.find_elements("xpath", "//span[contains(@class, 'my-objects-modal__max-count')]")
    state["modal_max_count"] = (
      (max_count_els[0].text or "").strip() if max_count_els else None
    )

    apply_btn = _find_csv_apply_button(driver)
    if apply_btn:
      state["apply_button"] = {
        "found": True,
        "displayed": apply_btn.is_displayed(),
        "enabled": apply_btn.is_enabled(),
      }
    else:
      state["apply_button"] = {"found": False}

    added = driver.find_elements("xpath", "//div[contains(text(), 'Добавлено объектов из CSV')]")
    state["objects_added_on_form"] = (
      (added[0].text or "").strip()[:300] if added else None
    )

    delete_btns = driver.find_elements("xpath", "//button[contains(@class, 'csv-control__btn-del')]")
    state["delete_button_visible"] = any(b.is_displayed() for b in delete_btns)

    upload_items = _get_csv_upload_items(driver)
    state["upload_list_count"] = len(upload_items)

    err_els = []
    for xpath in CSV_UPLOAD_ERROR_XPATHS:
      err_els = driver.find_elements("xpath", xpath)
      if err_els:
        break
    state["upload_error"] = next(
      ((el.text or "").strip() for el in err_els if (el.text or "").strip()),
      None,
    )

    modal_open = driver.find_elements("xpath", "//div[contains(@class, 'rros-ui-lib-modal__window')]")
    state["csv_modal_open"] = any(m.is_displayed() for m in modal_open)

  except Exception as e:
    state["_collect_error"] = str(e)

  return state

def _find_csv_apply_button(driver):
  """Кнопка «Применить» в модальном окне выбора объектов из CSV."""
  for btn in driver.find_elements("xpath", CSV_APPLY_BUTTON_XPATH):
    if "ПРИМЕНИТЬ" not in (btn.text or "").strip().upper():
      continue
    if btn.is_displayed() and btn.is_enabled():
      return btn
  return None


def _csv_modal_ready_to_apply(state):
  apply_info = state.get("apply_button") or {}
  if not (
    apply_info.get("found")
    and apply_info.get("enabled")
    and apply_info.get("displayed")
  ):
    return False
  if state.get("modal_max_count") == "0":
    return False
  return True


def _is_csv_warning_blocking(state):
  """
  «Объекты из CSV не добавлены в заявление» — штатное состояние формы до нажатия
  «Применить»; ошибкой считаем только если модальное окно не готово к применению.
  """
  if not state.get("csv_warning"):
    return False
  if state.get("objects_added_on_form"):
    return False
  if _csv_modal_ready_to_apply(state):
    return False
  return True


def wait_for_file_upload_by_title(driver, file_path):
    stage = "csv_upload"

    def _csv_error_result(state):
        if is_session_expired(driver):
            log_scenario(
                "session_expired_during_csv", stage, driver=driver, screenshot=True,
                message="Сессия истекла при загрузке CSV (401 / «Время сессии истекло»)",
                file_path=file_path,
                recommendation="Будет выполнена повторная авторизация",
            )
            return CSV_RESULT_SESSION_EXPIRED
        warning = state.get("csv_warning") if state else None
        log_scenario(
            "csv_objects_not_added", stage, driver=driver, screenshot=True,
            message=(
                f"Файл загружен в интерфейс, но объекты не добавлены"
                + (f": {warning}" if warning else "")
            ),
            file_path=file_path,
            recommendation=(
                "Проверьте формат CSV, кодировку, кадастровые номера. "
                "Возможно файл пустой или строки не прошли валидацию."
            ),
        )
        return CSV_RESULT_RETRY

    try:
        if is_session_expired(driver):
            return CSV_RESULT_SESSION_EXPIRED

        stale_items = _get_csv_upload_items(driver)
        if stale_items:
            log_warning(
                f"В списке загрузки CSV уже {len(stale_items)} файл(ов) — очищаем перед загрузкой",
                stage=stage, file=file_path.name,
            )
            clear_csv_upload_list(driver, file_path.name, stage=stage)
            remaining = _get_csv_upload_items(driver)
            if remaining:
                log_scenario(
                    "csv_upload_list_not_cleared", stage, driver=driver, screenshot=True,
                    message=f"Не удалось очистить список загрузки CSV (осталось {len(remaining)})",
                    file_path=file_path,
                    upload_list_count=len(remaining),
                )
                return CSV_RESULT_RETRY

        _send_csv_file(driver, file_path, stage=stage)
        log_info(
            f"Файл отправлен в input: {file_path.name}",
            stage=stage, file=file_path.name,
            csv_state=collect_csv_upload_state(driver, file_path),
        )

        # Ждём появления файла в списке или предупреждения об ошибке (не 1500 сек)
        try:
            WebDriverWait(driver, 60).until(lambda d: (
                d.find_elements(
                    "xpath",
                    f"//span[contains(@title, '{file_path.name}') "
                    f"and contains(@class, 'rros-ui-lib-file-upload__item__name')]",
                )
                or d.find_elements("xpath", "//div[contains(@class, 'csv-control__count-warn')]")
                or is_session_expired(d)
            ))
        except TimeoutException as e:
            if is_session_expired(driver):
                return CSV_RESULT_SESSION_EXPIRED
            log_scenario(
                "csv_file_not_in_list", stage, driver=driver, exc=e, screenshot=True,
                message="CSV-файл не появился в списке загрузки за 60 сек",
                file_path=file_path,
            )
            return CSV_RESULT_RETRY

        if is_session_expired(driver):
            return CSV_RESULT_SESSION_EXPIRED

        state = collect_csv_upload_state(driver, file_path)
        log_info(
            "Состояние CSV после появления файла в интерфейсе",
            stage=stage, file=file_path.name, **{k: v for k, v in state.items() if v is not None},
        )

        if _is_csv_warning_blocking(state):
            return _csv_error_result(state)

        if state.get("upload_error"):
            log_scenario(
                "csv_upload_rejected", stage, driver=driver, screenshot=True,
                message=f"Сайт отклонил загрузку CSV: {state['upload_error']}",
                file_path=file_path,
                upload_list_count=state.get("upload_list_count"),
                recommendation="Список загрузки будет очищен перед повторной попыткой",
            )
            return CSV_RESULT_RETRY

        time.sleep(2)
        log_info("Ожидание модального окна и кнопки «Применить»", stage=stage, file=file_path.name)

        deadline = time.time() + CSV_MODAL_TIMEOUT
        hard_deadline = deadline + CSV_MODAL_GRACE_WHILE_LOADING
        last_poll_log = 0
        confirm_button = None

        while time.time() < deadline or _is_csv_server_processing(driver):
            if time.time() >= hard_deadline:
                break
            if is_session_expired(driver):
                return CSV_RESULT_SESSION_EXPIRED

            state = collect_csv_upload_state(driver, file_path)

            apply_btn = _find_csv_apply_button(driver)
            if apply_btn:
                confirm_button = apply_btn
                if state.get("csv_warning"):
                    log_info(
                        "Модальное окно готово к «Применить» (предупреждение на форме до применения)",
                        stage=stage, file=file_path.name,
                        modal_max_count=state.get("modal_max_count"),
                    )
                break

            if _is_csv_warning_blocking(state):
                return _csv_error_result(state)

            if state.get("upload_error"):
                log_scenario(
                    "csv_upload_rejected", stage, driver=driver, screenshot=True,
                    message=f"Сайт отклонил загрузку CSV: {state['upload_error']}",
                    file_path=file_path,
                    upload_list_count=state.get("upload_list_count"),
                )
                return CSV_RESULT_RETRY

            if _is_csv_server_processing(driver) and time.time() >= deadline:
                if time.time() - last_poll_log >= CSV_POLL_INTERVAL:
                    elapsed = int(time.time() - (deadline - CSV_MODAL_TIMEOUT))
                    log_info(
                        f"Сервер обрабатывает CSV, продлеваем ожидание ({elapsed}/{CSV_MODAL_TIMEOUT}+{CSV_MODAL_GRACE_WHILE_LOADING} сек)",
                        stage=stage, file=file_path.name,
                    )
                    last_poll_log = time.time()

            if state.get("modal_max_count") == "0":
                if time.time() - last_poll_log >= CSV_POLL_INTERVAL:
                    log_warning(
                        "Модальное окно CSV открыто, но найдено 0 объектов",
                        stage=stage, driver=driver, file=file_path.name,
                        modal_max_count=0, modal_title=state.get("modal_title"),
                    )
                    last_poll_log = time.time()

            apply_info = state.get("apply_button", {})

            if time.time() - last_poll_log >= CSV_POLL_INTERVAL:
                elapsed = int(time.time() - (deadline - CSV_MODAL_TIMEOUT))
                log_info(
                    f"Ожидание кнопки «Применить» ({elapsed}/{CSV_MODAL_TIMEOUT} сек)",
                    stage=stage,
                    file=file_path.name,
                    modal_title=state.get("modal_title"),
                    modal_max_count=state.get("modal_max_count"),
                    apply_button=apply_info,
                    csv_modal_open=state.get("csv_modal_open"),
                )
                last_poll_log = time.time()

            time.sleep(2)

        if confirm_button is None:
            if is_session_expired(driver):
                return CSV_RESULT_SESSION_EXPIRED
            if _is_csv_server_processing(driver):
                log_scenario(
                    "csv_apply_button_timeout", stage, driver=driver, screenshot=True,
                    message=(
                        f"Кнопка «Применить» не появилась за {CSV_MODAL_TIMEOUT}+{CSV_MODAL_GRACE_WHILE_LOADING} сек, "
                        f"сервер всё ещё обрабатывает CSV."
                    ),
                    file_path=file_path,
                    timeout_sec=CSV_MODAL_TIMEOUT + CSV_MODAL_GRACE_WHILE_LOADING,
                    server_still_processing=True,
                )
                return CSV_RESULT_RETRY
            state = collect_csv_upload_state(driver, file_path)
            apply_btn = _find_csv_apply_button(driver)
            if apply_btn:
                confirm_button = apply_btn
            elif _is_csv_warning_blocking(state):
                return _csv_error_result(state)
            if confirm_button is not None:
                log_info(
                    "Кнопка «Применить» найдена после основного таймаута",
                    stage=stage, file=file_path.name,
                )
            else:
                log_scenario(
                    "csv_apply_button_timeout", stage, driver=driver, screenshot=True,
                    message=(
                        f"Кнопка «Применить» не появилась за {CSV_MODAL_TIMEOUT} сек. "
                        f"Возможно CSV не обработан сервером."
                    ),
                    file_path=file_path,
                    timeout_sec=CSV_MODAL_TIMEOUT,
                    **state,
                )
                return CSV_RESULT_RETRY

        log_info("Кнопка «Применить» найдена и кликабельна", stage=stage, file=file_path.name)
        driver.execute_script("arguments[0].click();", confirm_button)
        log_info("Кнопка «Применить» нажата", stage=stage, file=file_path.name)

        log_info("Ожидание закрытия модального окна", stage=stage)
        try:
            WebDriverWait(driver, 60).until(
                EC.invisibility_of_element_located(
                    ("xpath", "//div[contains(@class, 'rros-ui-lib-modal__window')]")
                )
            )
            log_info("Модальное окно CSV закрыто", stage=stage, file=file_path.name)
            return CSV_RESULT_SUCCESS

        except TimeoutException as e:
            log_warning(
                "Модальное окно CSV не закрылось автоматически",
                stage=stage, exc=e, driver=driver, file=file_path.name,
                csv_state=collect_csv_upload_state(driver, file_path),
            )
            if close_modal_window(driver):
                log_info("Модальное окно CSV закрыто вручную", stage=stage)
                return CSV_RESULT_SUCCESS
            log_scenario(
                "csv_modal_not_closed", stage, driver=driver, exc=e, screenshot=True,
                message="Не удалось закрыть модальное окно после нажатия «Применить»",
                file_path=file_path,
            )
            return CSV_RESULT_RETRY

    except Exception as e:
        if is_session_expired(driver):
            return CSV_RESULT_SESSION_EXPIRED
        log_scenario(
            "csv_upload_error", stage, driver=driver, exc=e, screenshot=True,
            message="Общая ошибка при загрузке CSV-файла",
            file_path=file_path,
        )
        return CSV_RESULT_RETRY

def _find_elements_by_xpaths(driver, xpaths):
    for xpath in xpaths:
        elements = driver.find_elements("xpath", xpath)
        if elements:
            return elements
    return []


def _is_csv_server_processing(driver):
    """Модальное окно «ЗАГРУЗКА ОБЪЕКТОВ» — сервер ещё обрабатывает CSV."""
    for modal in driver.find_elements("xpath", "//div[contains(@class, 'rros-ui-lib-modal__window')]"):
        if not modal.is_displayed():
            continue
        text = (modal.text or "").upper()
        if "ЗАГРУЗКА ОБЪЕКТОВ" in text or "ПОЖАЛУЙСТА, ПОДОЖДИТЕ" in text:
            return True
    return False


def _get_csv_upload_items(driver):
    """Реальные файлы в списке загрузки CSV (только items-list, не кнопка «Загрузить из CSV»)."""
    items = _find_elements_by_xpaths(driver, CSV_UPLOAD_ITEM_XPATHS)
    real_items = []
    for item in items:
        name_els = item.find_elements(
            "xpath", ".//span[contains(@class, 'rros-ui-lib-file-upload__item__name')]",
        )
        if not name_els:
            continue
        title = (name_els[0].get_attribute("title") or name_els[0].text or "").strip()
        if title and title != "Загрузить из CSV":
            real_items.append(item)
    return real_items


def _click_csv_upload_button(driver, stage="csv_upload"):
    """Нажимает «Загрузить из CSV» — без этого input может не принять файл."""
    for xpath in CSV_UPLOAD_BUTTON_XPATHS:
        for btn in driver.find_elements("xpath", xpath):
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                driver.execute_script("arguments[0].click();", btn)
                log_info("Кнопка «Загрузить из CSV» нажата", stage=stage)
                time.sleep(0.5)
                return True
            except Exception:
                pass
    log_warning("Кнопка «Загрузить из CSV» не найдена, пробуем input напрямую", stage=stage, driver=driver)
    return False


def _send_csv_file(driver, file_path, stage="csv_upload"):
    """Клик по кнопке загрузки CSV и отправка файла в input."""
    try:
        csv_input = driver.find_element("xpath", CSV_FILE_INPUT_XPATH)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", csv_input)
    except Exception:
        pass
    _click_csv_upload_button(driver, stage=stage)
    csv_input = driver.find_element("xpath", CSV_FILE_INPUT_XPATH)
    csv_input.send_keys(str(file_path))


def _count_csv_upload_list_items(driver):
    return len(_get_csv_upload_items(driver))


def _click_csv_upload_delete_buttons_js(driver):
    """Клик по корзинам в блоке CSV через JS (обходит is_displayed)."""
    return driver.execute_script("""
        const root = document.querySelector('.csv-control .rros-ui-lib-file-upload')
          || document.querySelector('.csv-control');
        if (!root) return 0;
        const buttons = root.querySelectorAll(
          '[data-test-id="FileUpload.delete"], .rros-ui-lib-file-upload__item-delete'
        );
        let clicked = 0;
        buttons.forEach(btn => { btn.click(); clicked += 1; });
        return clicked;
    """)


def clear_csv_upload_list(driver, file_name=None, stage="csv_upload"):
    """Удаляет файлы из списка загрузки CSV (иконки корзины), не трогая PDF и подпись."""
    close_modal_window(driver)
    close_address_modals(driver, stage=stage)
    time.sleep(0.5)

    try:
        csv_input = driver.find_element("xpath", CSV_FILE_INPUT_XPATH)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", csv_input)
        time.sleep(0.3)
    except Exception:
        pass

    removed = 0
    for round_idx in range(15):
        count_before = _count_csv_upload_list_items(driver)
        if count_before == 0:
            break

        clicked_this_round = 0
        for xpath in CSV_UPLOAD_DELETE_XPATHS:
            for btn in driver.find_elements("xpath", xpath):
                try:
                    driver.execute_script("arguments[0].click();", btn)
                    removed += 1
                    clicked_this_round += 1
                    time.sleep(0.3)
                except Exception as e:
                    log_warning(
                        "Не удалось нажать удаление файла из списка загрузки CSV",
                        stage=stage, exc=e, driver=driver, file=file_name,
                    )

        if clicked_this_round == 0:
            js_clicked = _click_csv_upload_delete_buttons_js(driver) or 0
            removed += js_clicked
            clicked_this_round = js_clicked

        time.sleep(0.5)
        count_after = _count_csv_upload_list_items(driver)
        if count_after == 0:
            break
        if count_after >= count_before and clicked_this_round == 0:
            log_warning(
                "Не удалось удалить файлы из списка загрузки CSV",
                stage=stage, driver=driver, file=file_name,
                items_remaining=count_after, round=round_idx + 1,
            )
            break

    if removed:
        log_info(
            f"Удалено файлов из списка загрузки CSV: {removed}",
            stage=stage, file=file_name, remaining=_count_csv_upload_list_items(driver),
        )
    elif _count_csv_upload_list_items(driver) > 0:
        log_warning(
            "Список загрузки CSV не очищен",
            stage=stage, driver=driver, file=file_name,
            items_remaining=_count_csv_upload_list_items(driver),
        )
    return removed > 0 and _count_csv_upload_list_items(driver) == 0


def remove_csv_from_interface(driver, file_name, stage="csv_upload"):
    """Удаляет CSV из интерфейса: модалки, список загрузки, затем кнопка «Удалить» на форме."""
    cleared = clear_csv_upload_list(driver, file_name, stage=stage)

    delete_xpath = "//button[contains(@class, 'csv-control__btn-del') and contains(., 'Удалить')]"
    try:
        delete_buttons = driver.find_elements("xpath", delete_xpath)
        for btn in delete_buttons:
            if btn.is_displayed():
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                driver.execute_script("arguments[0].click();", btn)
                log_info("Кнопка 'Удалить' нажата (JS)", stage=stage, file=file_name)
                try:
                    WebDriverWait(driver, 15).until(
                        EC.invisibility_of_element_located((
                            "xpath",
                            f"//span[contains(@title, '{file_name}') "
                            f"and contains(@class, 'rros-ui-lib-file-upload__item__name')]",
                        ))
                    )
                    log_info("Файл удалён из интерфейса", stage=stage, file=file_name)
                except Exception as e:
                    log_warning(
                        "Файл не исчез из интерфейса после удаления",
                        stage=stage, exc=e, driver=driver, file=file_name,
                    )
                return True
    except Exception as e:
        log_exception(
            stage, e, driver=driver, screenshot=True,
            screenshot_name=f"csv_delete_error_{file_name}.png",
            message="Не удалось нажать кнопку 'Удалить'",
            file=file_name,
        )

    if cleared:
        log_info("Список загрузки CSV очищен", stage=stage, file=file_name)
        return True

    remaining = _count_csv_upload_list_items(driver)
    if remaining > 0:
        log_warning(
            f"В списке загрузки CSV осталось файлов: {remaining}",
            stage=stage, driver=driver, file=file_name,
        )
    return remaining == 0


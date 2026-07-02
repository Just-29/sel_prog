import atexit
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import *

# --- Логирование ---
LOG_DIR = Path(__file__).parent / "selenium_notes"
LOG_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR = LOG_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
DIAGNOSTICS_DIR = LOG_DIR / "diagnostics"
DIAGNOSTICS_DIR.mkdir(exist_ok=True)

SESSION_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
_session_events = []
_session_report_written = False

_LOG_FORMAT = "[%(asctime)s] %(levelname)-8s | %(stage)s | %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _StageFilter(logging.Filter):
  def filter(self, record):
    if not hasattr(record, "stage"):
      record.stage = "-"
    return True


def _setup_logger():
  logger = logging.getLogger("rosreestr")
  if logger.handlers:
    return logger

  logger.setLevel(logging.DEBUG)
  stage_filter = _StageFilter()

  formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

  run_handler = logging.FileHandler(LOG_DIR / "run.log", encoding="utf-8")
  run_handler.setLevel(logging.DEBUG)
  run_handler.setFormatter(formatter)
  run_handler.addFilter(stage_filter)

  error_handler = logging.FileHandler(LOG_DIR / "errors.log", encoding="utf-8")
  error_handler.setLevel(logging.WARNING)
  error_handler.setFormatter(formatter)
  error_handler.addFilter(stage_filter)

  console_handler = logging.StreamHandler(sys.stdout)
  console_handler.setLevel(logging.INFO)
  console_handler.setFormatter(formatter)
  console_handler.addFilter(stage_filter)

  logger.addHandler(run_handler)
  logger.addHandler(error_handler)
  logger.addHandler(console_handler)
  return logger


logger = _setup_logger()

ERROR_HINTS = {
  TimeoutException: "Элемент не появился вовремя. Проверьте сеть, увеличьте timeout или дождитесь полной загрузки страницы.",
  NoSuchElementException: "Элемент не найден в DOM. Возможно изменился UI — проверьте XPath/CSS локаторы.",
  ElementClickInterceptedException: "Клик перехвачен другим элементом (модальное окно, overlay). Закройте мешающие окна или используйте JS-клик.",
  ElementNotInteractableException: "Элемент есть, но недоступен для ввода. Проверьте видимость, enabled-состояние и перекрытие.",
  StaleElementReferenceException: "Элемент устарел после обновления DOM. Повторно найдите элемент перед действием.",
  WebDriverException: "Ошибка WebDriver/браузера. Проверьте Chrome, chromedriver и профиль браузера.",
}


def _get_driver_context(driver=None):
  ctx = {}
  if driver is None:
    return ctx
  try:
    ctx["url"] = driver.current_url
  except Exception as e:
    ctx["url_error"] = str(e)
  try:
    ctx["title"] = driver.title
  except Exception as e:
    ctx["title_error"] = str(e)
  try:
    ctx["ready_state"] = driver.execute_script("return document.readyState")
  except Exception:
    pass
  try:
    size = driver.get_window_size()
    ctx["window"] = f"{size['width']}x{size['height']}"
  except Exception:
    pass
  try:
    ctx["scroll"] = driver.execute_script(
      "return {x: window.scrollX, y: window.scrollY, h: document.body.scrollHeight}"
    )
  except Exception:
    pass
  return ctx


def _safe_driver_call(driver, fn, default=None):
  try:
    return fn()
  except Exception as e:
    return {"_error": f"{type(e).__name__}: {e}"} if default is None else default


def collect_page_diagnostics(driver):
  """Собирает с сайта всё, что помогает понять состояние страницы при ошибке."""
  if driver is None:
    return {}

  diag = {
    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "browser": _get_driver_context(driver),
  }

  # Сообщения об ошибках на странице Росреестра
  ui_error_xpaths = [
    "//div[contains(@class, 'rros-ui-lib-errors')]",
    "//div[contains(@class, 'rros-ui-lib-error')]",
    "//div[contains(@class, 'error-message')]",
    "//div[contains(@class, 'toast')]",
    "//div[contains(@class, 'notification')]",
    "//*[contains(@class, 'alert')]",
    "//span[contains(@class, 'error')]",
  ]
  ui_errors = []
  for xpath in ui_error_xpaths:
    try:
      for el in driver.find_elements("xpath", xpath):
        text = (el.text or "").strip()
        if text and text not in ui_errors:
          ui_errors.append({"xpath": xpath, "text": text[:1000]})
    except Exception:
      pass
  diag["ui_errors"] = ui_errors

  # Модальные окна
  modals = []
  modal_xpaths = [
    "//div[contains(@class, 'rros-ui-lib-modal__window')]",
    "//div[contains(@class, 'modal') and contains(@class, 'window')]",
  ]
  for xpath in modal_xpaths:
    try:
      for el in driver.find_elements("xpath", xpath):
        if el.is_displayed():
          modals.append({
            "xpath": xpath,
            "visible": True,
            "text": (el.text or "")[:2000],
          })
    except Exception:
      pass
  diag["modals"] = modals

  # Индикаторы загрузки
  loading = []
  loading_xpaths = [
    "//div[contains(@class, 'loading')]",
    "//div[contains(@class, 'spinner')]",
    "//div[contains(@class, 'rros-ui-lib-loading')]",
    "//*[contains(text(), 'Загрузка')]",
  ]
  for xpath in loading_xpaths:
    try:
      for el in driver.find_elements("xpath", xpath):
        if el.is_displayed():
          loading.append({"xpath": xpath, "text": (el.text or "")[:200]})
    except Exception:
      pass
  diag["loading_indicators"] = loading

  # Значения полей формы (все видимые input/select/textarea)
  diag["form_fields"] = _safe_driver_call(driver, lambda: driver.execute_script("""
    return Array.from(document.querySelectorAll('input, select, textarea'))
      .map(el => ({
        tag: el.tagName,
        id: el.id || null,
        name: el.name || null,
        type: el.type || null,
        value: String(el.value || '').slice(0, 300),
        placeholder: el.placeholder || null,
        disabled: !!el.disabled,
        readOnly: !!el.readOnly,
        visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
        ariaInvalid: el.getAttribute('aria-invalid'),
      }))
      .filter(f => f.id || f.name || f.value)
      .slice(0, 150);
  """), default=[])

  # React-select поля
  diag["react_selects"] = _safe_driver_call(driver, lambda: driver.execute_script("""
    return Array.from(document.querySelectorAll('input[id*="react-select"]'))
      .map(el => ({
        id: el.id,
        value: el.value,
        ariaExpanded: el.getAttribute('aria-expanded'),
        visible: !!(el.offsetWidth || el.offsetHeight),
      }));
  """), default=[])

  # Кнопки (видимые, disabled)
  diag["buttons"] = _safe_driver_call(driver, lambda: driver.execute_script("""
    return Array.from(document.querySelectorAll('button'))
      .filter(el => el.offsetParent !== null)
      .map(el => ({
        text: (el.innerText || '').trim().slice(0, 80),
        disabled: el.disabled,
        class: (el.className || '').slice(0, 120),
      }))
      .slice(0, 50);
  """), default=[])

  # Загруженные файлы в интерфейсе
  diag["uploaded_files"] = _safe_driver_call(driver, lambda: [
    (el.get_attribute("title") or el.text or "").strip()[:200]
    for el in driver.find_elements(
      "xpath",
      "//span[contains(@class, 'rros-ui-lib-file-upload__item__name')]",
    )
  ], default=[])

  # CSV-статус
  try:
    csv_status_els = driver.find_elements(
      "xpath",
      "//div[contains(text(), 'Добавлено объектов из CSV') or contains(text(), 'CSV')]",
    )
    diag["csv_status"] = [
      (el.text or "").strip()[:500]
      for el in csv_status_els
      if (el.text or "").strip()
    ]
  except Exception as e:
    diag["csv_status"] = {"_error": str(e)}

  # Консоль браузера (последние записи)
  try:
    console_logs = driver.get_log("browser")
    diag["console_logs"] = [
      {
        "level": entry.get("level"),
        "message": entry.get("message", "")[:500],
        "timestamp": entry.get("timestamp"),
      }
      for entry in console_logs[-30:]
    ]
  except Exception as e:
    diag["console_logs"] = {"_error": str(e), "_hint": "Включите goog:loggingPrefs при запуске Chrome"}

  # Ключевые фрагменты DOM для быстрого анализа
  diag["dom_hints"] = _safe_driver_call(driver, lambda: driver.execute_script("""
    const hints = {};
    const ids = [
      'applicantCategory', 'react-select-3-input', 'react-select-6-input',
      'userAuthorityConfirmationDocument.documentType',
    ];
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) {
        hints[id] = {
          value: String(el.value || '').slice(0, 200),
          visible: !!(el.offsetWidth || el.offsetHeight),
          disabled: !!el.disabled,
        };
      } else {
        hints[id] = null;
      }
    }
    hints.address_menu = !!document.evaluate(
      "(//div[text()='Заполните адрес'])[1]",
      document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
    ).singleNodeValue;
    hints.submit_button = !!document.evaluate(
      "//button[text()='Далее']",
      document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
    ).singleNodeValue;
  return hints;
  """), default={})

  diag["csv_upload"] = collect_csv_upload_state(driver)
  diag["address"] = collect_address_state(driver)

  return diag


CSV_FILE_INPUT_XPATH = "//div[contains(@class, 'csv-control')]//input[@type='file']"
CSV_UPLOAD_ROOT_XPATH = "//div[contains(@class, 'csv-control')]//div[contains(@class, 'rros-ui-lib-file-upload')]"
CSV_UPLOAD_BUTTON_XPATHS = (
    "//div[contains(@class, 'csv-control')]//div[@data-test-id='FileUpload.button']",
    "//div[contains(@class, 'csv-control')]//div[contains(@class, 'rros-ui-lib-file-upload__simple-button')][contains(., 'Загрузить из CSV')]",
)
CSV_UPLOAD_ITEM_XPATHS = (
    "//div[contains(@class, 'csv-control')]//div[contains(@class, 'rros-ui-lib-file-upload__items-list')]//div[contains(@class, 'rros-ui-lib-file-upload__item')]",
    "//div[contains(@class, 'csv-control')]//div[@data-cy='file-upload-item']",
)
CSV_UPLOAD_DELETE_XPATHS = (
    f"{CSV_UPLOAD_ROOT_XPATH}//span[@data-test-id='FileUpload.delete']",
    f"{CSV_UPLOAD_ROOT_XPATH}//span[contains(@class, 'rros-ui-lib-file-upload__item-delete')]",
    "//div[contains(@class, 'csv-control')]//span[@data-test-id='FileUpload.delete']",
    "//div[contains(@class, 'csv-control')]//span[contains(@class, 'rros-ui-lib-file-upload__item-delete')]",
)
CSV_UPLOAD_ERROR_XPATHS = (
    f"{CSV_UPLOAD_ROOT_XPATH}//div[contains(@class, 'rros-ui-lib-file-upload__message_error')]",
    "//div[contains(@class, 'csv-control')]//div[contains(@class, 'rros-ui-lib-file-upload__message_error')]",
)
CSV_MODAL_TIMEOUT = 300
CSV_MODAL_GRACE_WHILE_LOADING = 120
CSV_POLL_INTERVAL = 10
CSV_RESULT_SUCCESS = "success"
CSV_RESULT_RETRY = "retry"
CSV_RESULT_SESSION_EXPIRED = "session_expired"
SESSION_EXPIRED_MARKERS = ("Время сессии истекло", "сессии истекло")
CSV_APPLY_BUTTON_XPATH = "//button[contains(@class, 'my-objects-modal__selected-btn')]"


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


ADDRESS_MODAL_XPATH = "//div[contains(@class, 'rros-ui-lib-modal__window')]"
_REACT_SELECT_INPUT_XPATH = ".//input[starts-with(@id, 'react-select-') and contains(@id, '-input')]"
ADDRESS_INPUT_XPATH = f"{ADDRESS_MODAL_XPATH}{_REACT_SELECT_INPUT_XPATH[1:]}"
ADDRESS_SAVE_XPATH = f"{ADDRESS_MODAL_XPATH}//button[normalize-space(text())='Сохранить']"
ADDRESS_OPTION_XPATHS = (
    "//div[contains(@id, 'react-select') and contains(@id, '-option-')]",
    f"{ADDRESS_MODAL_XPATH}//div[contains(@class, 'rros-ui-lib-dropdown__option')]",
    "//div[contains(@class, 'rros-ui-lib-dropdown__option')]",
)
_MODAL_BUTTON_LABELS = {
    "save": ("СОХРАНИТЬ", "Сохранить"),
    "cancel": ("ОТМЕНА", "Отмена"),
}


def collect_address_state(driver):
  """Снимок состояния поля адреса — для диагностики проблем с react-select."""
  state = {}
  try:
    fill = driver.find_elements(
      "xpath", "//div[@id='realEstateItems']//div[text()='Заполните адрес']"
    )
    state["fill_address_prompt_visible"] = bool(fill and fill[0].is_displayed())

    modal = None
    modals = [m for m in driver.find_elements(
      "xpath", "//div[contains(@class, 'rros-ui-lib-modal__window')]"
    ) if m.is_displayed()]
    state["address_modal_open"] = len(modals) > 0
    if modals:
      modal = modals[-1]
      state["address_modal_text"] = (modal.text or "")[:500]
      modal_inputs = modal.find_elements("xpath", _REACT_SELECT_INPUT_XPATH)
      state["modal_react_select_inputs"] = [
        {
          "id": (inp.get_attribute("id") or "")[:80],
          "value": (inp.get_attribute("value") or "")[:200],
          "enabled": inp.is_enabled(),
          "displayed": inp.is_displayed(),
        }
        for inp in modal_inputs[:5]
      ]

    for sel_id in ("react-select-3-input", "react-select-2-input"):
      els = driver.find_elements("xpath", f"//input[@id='{sel_id}']")
      if els:
        el = els[0]
        state[sel_id] = {
          "value": (el.get_attribute("value") or "")[:200],
          "enabled": el.is_enabled(),
          "displayed": el.is_displayed(),
          "aria_expanded": el.get_attribute("aria-expanded"),
        }

    options = driver.find_elements("xpath", "//div[contains(@class, 'rros-ui-lib-dropdown__option')]")
    state["dropdown_options_count"] = len([o for o in options if o.is_displayed()])

    menu_options = driver.find_elements(
      "xpath", "//div[contains(@id, 'react-select') and contains(@id, '-option-')]",
    )
    state["react_select_options_count"] = len([o for o in menu_options if o.is_displayed()])

    single_values = driver.find_elements("xpath", "//div[contains(@class, 'rros-ui-lib-dropdown__single-value')]")
    state["selected_values"] = [
      (v.text or "").strip()[:200]
      for v in single_values
      if (v.text or "").strip()
    ][:5]

    save_btns = driver.find_elements("xpath", ADDRESS_SAVE_XPATH)
    if not save_btns:
      save_btns = driver.find_elements("xpath", "//button[normalize-space(text())='Сохранить']")
    if save_btns:
      state["save_button"] = {
        "found": True,
        "displayed": save_btns[0].is_displayed(),
        "enabled": save_btns[0].is_enabled(),
      }

  except Exception as e:
    state["_collect_error"] = str(e)

  return state


def log_scenario(scenario, stage, driver=None, message=None, exc=None, screenshot=False, **context):
  """Именованный сценарий ошибки с полной диагностикой CSV/адреса."""
  if driver is not None:
    if stage == "csv_upload" or scenario.startswith("csv_"):
      fp = context.pop("file_path", None)
      context["csv_state"] = collect_csv_upload_state(driver, fp)
      if fp is not None:
        context["file"] = fp.name if hasattr(fp, "name") else str(fp)
    if stage == "address" or scenario.startswith("address_"):
      context["address_state"] = collect_address_state(driver)

  msg = message or f"Сценарий: {scenario}"
  log_error(
    msg, stage=stage, exc=exc, driver=driver,
    screenshot=screenshot, scenario=scenario, **context,
  )


def save_diagnostic_bundle(driver, stage, message, exc=None, screenshot=False, screenshot_name=None, **context):
  """Сохраняет полный пакет диагностики: JSON + HTML + скриншот."""
  ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
  safe_stage = "".join(c if c.isalnum() or c in "-_" else "_" for c in stage)
  base_name = f"{SESSION_ID}_{safe_stage}_{ts}"

  bundle = {
    "session_id": SESSION_ID,
    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "stage": stage,
    "message": message,
    "context": context,
    "files": {},
  }

  if exc is not None:
    bundle["exception"] = {
      "type": type(exc).__name__,
      "message": str(exc),
      "traceback": traceback.format_exc(),
    }
    for exc_type, hint in ERROR_HINTS.items():
      if isinstance(exc, exc_type):
        bundle["recommendation"] = hint
        break

  if driver is not None:
    bundle["page"] = collect_page_diagnostics(driver)

    # HTML-снимок страницы
    try:
      html_path = DIAGNOSTICS_DIR / f"{base_name}.html"
      html_path.write_text(driver.page_source, encoding="utf-8")
      bundle["files"]["html"] = str(html_path)
    except Exception as e:
      bundle["files"]["html_error"] = str(e)

    if screenshot:
      try:
        name = screenshot_name or f"{base_name}.png"
        screenshot_path = SCREENSHOTS_DIR / name
        driver.save_screenshot(str(screenshot_path))
        bundle["files"]["screenshot"] = str(screenshot_path)
      except Exception as e:
        bundle["files"]["screenshot_error"] = str(e)

  json_path = DIAGNOSTICS_DIR / f"{base_name}.json"
  try:
    json_path.write_text(
      json.dumps(bundle, ensure_ascii=False, indent=2, default=str),
      encoding="utf-8",
    )
    bundle["files"]["json"] = str(json_path)
  except Exception as e:
    logger.error(f"Не удалось сохранить JSON-диагностику: {e}", extra={"stage": stage})

  _session_events.append(bundle)
  return bundle


def write_session_report():
  """Итоговый отчёт по сессии — для анализа всех ошибок после завершения скрипта."""
  global _session_report_written
  if _session_report_written:
    return None
  _session_report_written = True
  report_path = LOG_DIR / f"session_{SESSION_ID}.md"
  errors = [e for e in _session_events if "exception" in e]
  warnings_count = len(_session_events) - len(errors)

  lines = [
    f"# Отчёт сессии {SESSION_ID}",
    f"",
    f"**Завершено:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    f"**Всего событий диагностики:** {len(_session_events)}",
    f"**Ошибок с исключениями:** {len(errors)}",
    f"",
    f"## Файлы",
    f"- Полный лог: `run.log`",
    f"- Только ошибки: `errors.log`",
    f"- Диагностика: `diagnostics/` ({len(list(DIAGNOSTICS_DIR.glob(f'{SESSION_ID}_*.json')))} JSON-пакетов)",
    f"- Скриншоты: `screenshots/`",
    f"",
  ]

  if not _session_events:
    lines.append("Ошибок с диагностикой не зафиксировано.")
  else:
    lines.append("## События (по порядку)")
    lines.append("")
    for i, event in enumerate(_session_events, 1):
      lines.append(f"### {i}. [{event['stage']}] {event['message']}")
      lines.append(f"- **Время:** {event['timestamp']}")
      ctx = event.get("context", {})
      if ctx.get("scenario"):
        lines.append(f"- **Сценарий:** `{ctx['scenario']}`")
      if "exception" in event:
        ex = event["exception"]
        lines.append(f"- **Ошибка:** `{ex['type']}: {ex['message']}`")
      if event.get("recommendation"):
        lines.append(f"- **Рекомендация:** {event['recommendation']}")
      if event.get("context"):
        ctx_items = {k: v for k, v in event["context"].items() if k not in ("csv_state", "address_state")}
        if ctx_items:
          lines.append(f"- **Контекст:** {', '.join(f'{k}={v}' for k, v in ctx_items.items())}")
      csv_st = ctx.get("csv_state") or event.get("page", {}).get("csv_upload")
      if csv_st:
        if csv_st.get("csv_warning"):
          lines.append(f"- **CSV на сайте:** {csv_st['csv_warning']}")
        if csv_st.get("modal_max_count") is not None:
          lines.append(f"- **Объектов в модальном окне:** {csv_st['modal_max_count']}")
      addr_st = ctx.get("address_state") or event.get("page", {}).get("address")
      if addr_st:
        if addr_st.get("fill_address_prompt_visible"):
          lines.append("- **Адрес:** не заполнен («Заполните адрес» видно)")
        if addr_st.get("dropdown_options_count") == 0 and addr_st.get("react_select_options_count") == 0:
          lines.append("- **Адрес:** варианты в выпадающем списке не появились")

      page = event.get("page", {})
      if page.get("ui_errors"):
        lines.append("- **Ошибки на сайте:**")
        for err in page["ui_errors"][:5]:
          lines.append(f"  - {err['text'][:200]}")
      if page.get("modals"):
        lines.append(f"- **Открытые модальные окна:** {len(page['modals'])}")
        for m in page["modals"][:2]:
          preview = m.get("text", "")[:150].replace("\n", " ")
          lines.append(f"  - {preview}")
      if page.get("loading_indicators"):
        lines.append(f"- **Активные индикаторы загрузки:** {len(page['loading_indicators'])}")
      if page.get("console_logs") and isinstance(page["console_logs"], list):
        severe = [l for l in page["console_logs"] if l.get("level") in ("SEVERE", "WARNING")]
        if severe:
          lines.append("- **Консоль браузера:**")
          for log in severe[-5:]:
            lines.append(f"  - [{log['level']}] {log['message'][:150]}")

      files = event.get("files", {})
      if files.get("json"):
        lines.append(f"- **JSON:** `{files['json']}`")
      if files.get("html"):
        lines.append(f"- **HTML:** `{files['html']}`")
      if files.get("screenshot"):
        lines.append(f"- **Скриншот:** `{files['screenshot']}`")
      lines.append("")

  report_path.write_text("\n".join(lines), encoding="utf-8")
  log_info(f"Итоговый отчёт сессии: {report_path}", stage="shutdown", events=len(_session_events))
  return report_path


def _format_context(**context):
  if not context:
    return ""
  parts = [f"{k}={v}" for k, v in context.items()]
  return " | " + ", ".join(parts)


def log_info(message, stage="-", **context):
  logger.info(message + _format_context(**context), extra={"stage": stage})


def log_warning(message, stage="-", exc=None, driver=None, capture_diagnostics=False, **context):
  text = message
  if exc is not None:
    text += f" | {type(exc).__name__}: {exc}"
  text += _format_context(**context)
  logger.warning(text, extra={"stage": stage})

  if driver is not None and capture_diagnostics:
    save_diagnostic_bundle(driver, stage, message, exc=exc, screenshot=False, **context)


def log_error(
  message,
  stage="-",
  exc=None,
  driver=None,
  screenshot=False,
  screenshot_name=None,
  capture_diagnostics=True,
  **context,
):
  """Полное логирование ошибки: тип, текст, traceback, контекст браузера, диагностика с сайта."""
  context = {**_get_driver_context(driver), **context}
  lines = [message]

  if exc is not None:
    lines.append(f"Тип: {type(exc).__name__}")
    lines.append(f"Сообщение: {exc}")
    hint = None
    for exc_type, exc_hint in ERROR_HINTS.items():
      if isinstance(exc, exc_type):
        hint = exc_hint
        break
    if hint:
      lines.append(f"Рекомендация: {hint}")
    tb = traceback.format_exc()
    if tb and tb.strip() != "NoneType: None":
      lines.append(f"Traceback:\n{tb.rstrip()}")

  # Краткая сводка с сайта прямо в лог
  if driver is not None and capture_diagnostics:
    try:
      page_diag = collect_page_diagnostics(driver)
      if page_diag.get("ui_errors"):
        lines.append("Ошибки на сайте:")
        for err in page_diag["ui_errors"][:5]:
          lines.append(f"  • {err['text'][:300]}")
      if page_diag.get("modals"):
        lines.append(f"Открытых модальных окон: {len(page_diag['modals'])}")
      if page_diag.get("loading_indicators"):
        lines.append(f"Активных индикаторов загрузки: {len(page_diag['loading_indicators'])}")
      dom = page_diag.get("dom_hints", {})
      if isinstance(dom, dict) and "_error" not in dom:
        missing = [k for k, v in dom.items() if v is None]
        if missing:
          lines.append(f"Отсутствуют ключевые элементы: {', '.join(missing)}")
    except Exception as diag_err:
      lines.append(f"Не удалось собрать краткую диагностику: {diag_err}")

  lines.append(f"Контекст:{_format_context(**context)}")
  full_message = "\n".join(lines)
  logger.error(full_message, extra={"stage": stage})

  bundle = None
  if driver is not None and capture_diagnostics:
    bundle = save_diagnostic_bundle(
      driver, stage, message, exc=exc,
      screenshot=screenshot, screenshot_name=screenshot_name,
      **context,
    )
    if bundle and bundle.get("files", {}).get("json"):
      logger.error(f"Диагностический пакет: {bundle['files']['json']}", extra={"stage": stage})
  elif screenshot and driver is not None:
    try:
      name = screenshot_name or f"error_{stage}_{int(time.time())}.png"
      screenshot_path = SCREENSHOTS_DIR / name
      driver.save_screenshot(str(screenshot_path))
      logger.error(f"Скриншот сохранён: {screenshot_path}", extra={"stage": stage})
    except Exception as shot_err:
      logger.error(
        f"Не удалось сохранить скриншот: {type(shot_err).__name__}: {shot_err}",
        extra={"stage": stage},
      )

  return bundle


def log_exception(stage, exc, driver=None, message=None, screenshot=False, capture_diagnostics=True, **context):
  """Удобная обёртка для except-блоков."""
  msg = message or f"Исключение в этапе «{stage}»"
  return log_error(
    msg, stage=stage, exc=exc, driver=driver,
    screenshot=screenshot, capture_diagnostics=capture_diagnostics,
    **context,
  )

log_info(f"Сессия диагностики: {SESSION_ID}", stage="init")
atexit.register(write_session_report)

# //div[@class='rros-ui-lib-errors'] див ошибок
# //button[@class='rros-ui-lib-button rros-ui-lib-button--link'] крестик для закрытия сообщений об ошибке
# Закрываем все процессы Chrome перед запуском
log_info("Завершение процессов Chrome/chromedriver перед запуском", stage="init")
os.system('taskkill /f /im chrome.exe 2>nul')
os.system('taskkill /f /im chromedriver.exe 2>nul')
time.sleep(2)

# Отключаем логи только webdriver-manager
os.environ['WDM_LOG_LEVEL'] = '0'

chrome_options = Options()
chrome_options.binary_location = CHROME_PATH

# Путь к профию, с установленными расширениями
chrome_options.add_argument(F"--user-data-dir={CHROME_PROFILE_PATH}")
chrome_options.add_argument("--profile-directory=Default")

# Отключение логов
chrome_options.add_argument("--log-level=0")
chrome_options.add_argument("--disable-logging")
chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
chrome_options.set_capability("goog:loggingPrefs", {"browser": "ALL", "driver": "WARNING"})


service = Service(
    executable_path=DRIVER_PATH,
    log_path='NUL'  # Перенаправляем логи ChromeDriver в никуда
)

try:
    driver = webdriver.Chrome(service=service, options=chrome_options)
    log_info("WebDriver успешно запущен", stage="init", chrome_path=CHROME_PATH)
except Exception as e:
    log_error("Не удалось запустить WebDriver", stage="init", exc=e, screenshot=False)
    raise

wait = WebDriverWait(driver, 1500, poll_frequency=1)


script_dir = Path(__file__).parent
file_path = os.path.join(script_dir, "uploads", PDF_FILE_NAME)
file_signature = os.path.join(script_dir, "uploads", SIGNATURE_FILE_NAME)
uploads_file_dir = script_dir / "uploads" / "uploads_files"

actions = ActionChains(driver)

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


def save_selenium_note(driver, message, screenshot=False):
    """Сохраняет заметку для Selenium с возможностью скриншота"""
    note_file = LOG_DIR / "actions.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(note_file, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {message}\n")

    level = logging.INFO if "УСПЕХ" in message else logging.ERROR
    logger.log(level, message, extra={"stage": "result"})

    if screenshot and driver is not None:
        try:
            path = SCREENSHOTS_DIR / f"note_{int(time.time())}.png"
            driver.save_screenshot(str(path))
            log_info(f"Скриншот к заметке: {path}", stage="result")
        except Exception as e:
            log_warning("Не удалось сделать скриншот для заметки", stage="result", exc=e)

LOGIN_MINISTRY = "МИНИСТЕРСТВО ЖИЛИЩНО-КОММУНАЛЬНОГО ХОЗЯЙСТВА"
LOGIN_MINISTRY_FULL = (
    "МИНИСТЕРСТВО ЖИЛИЩНО-КОММУНАЛЬНОГО ХОЗЯЙСТВА, "
    "ТОПЛИВА И ЭНЕРГЕТИКИ РЕСПУБЛИКИ СЕВЕРНАЯ ОСЕТИЯ-АЛАНИЯ"
)
LOGIN_EDS_BUTTON_XPATHS = (
    "//button[contains(., 'Электронная подпись')]",
    "//button[@aria-label='Эл. подпись']",
)
LOGIN_CONTINUE_XPATHS = ("//button[contains(., 'Продолжить')]",)
LOGIN_MINISTRY_XPATHS = (
    f"//button[contains(., '{LOGIN_MINISTRY}')]",
    f"//h3[contains(@class, 'eds-card__title') and contains(., '{LOGIN_MINISTRY}')]",
)
LOGIN_ROLE_XPATHS = (
    f"//span[text()='{LOGIN_MINISTRY_FULL}']",
    "//div[contains(@class, 'role-selector-list__item-content')]"
    f"[.//span[contains(@class, 'role-selector-list__item-name') and contains(., '{LOGIN_MINISTRY}')]]",
)
LOGIN_EDS_SCREEN_XPATHS = (
    "//button[text()=' Восстановить ']",
    "//h1[contains(., 'QR-код')]",
)


def _login_form_loaded(driver):
    return bool(driver.find_elements("xpath", "//input[@id='applicantCategory']"))


def _login_wait_click(wait, xpaths, stage, label):
    combined = " | ".join(f"({xpath})" for xpath in xpaths)
    wait.until(EC.element_to_be_clickable(("xpath", combined))).click()
    log_info(label, stage=stage)


def _login_via_eds(driver, wait, stage):
    _login_wait_click(wait, LOGIN_EDS_BUTTON_XPATHS, stage, "Нажата кнопка электронной подписи")
    time.sleep(5)
    _login_wait_click(wait, LOGIN_CONTINUE_XPATHS, stage, "Нажата кнопка Продолжить")
    time.sleep(5)
    _login_wait_click(wait, LOGIN_MINISTRY_XPATHS, stage, "Выбрано МИНИСТЕРСТВО ЖКХ")
    time.sleep(10)
    _login_wait_click(wait, LOGIN_ROLE_XPATHS, stage, "Выбран пользователь (ЭП)")
    time.sleep(5)


def login_funct(driver):
    stage = "login"
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


REAL_ESTATE_SECTION = "#realEstateItems"
APPLICANT_PERSON_SECTION = "fullNameDocumentAndAdditionalInformationArray[0]"
APPLICANT_RESIDENCE_MODAL_CONTENT_ID = f"{APPLICANT_PERSON_SECTION}.fiasAddress--modal-content"
OBJECT_ADDRESS_OPEN_XPATHS = (
    "//div[@id='realEstateItems']//div[contains(@class, 'fias-address-select__btn-filling')]",
    "//div[@id='realEstateItems']//div[text()='Заполните адрес']",
    "(//div[text()='Заполните адрес'])[1]",
)
APPLICANT_RESIDENCE_OPEN_XPATHS = (
    f"//div[contains(@id, '{APPLICANT_PERSON_SECTION}')]//div[contains(@class, 'fias-address-select__btn-filling')]",
    f"//div[contains(@id, '{APPLICANT_PERSON_SECTION}')]//div[contains(@class, 'fias-address-select__address-text--req')]",
    f"//div[contains(@id, '{APPLICANT_PERSON_SECTION}')]//div[text()='Заполните адрес']",
)
OBJECT_ADDRESS_OPEN_XPATH = " | ".join(OBJECT_ADDRESS_OPEN_XPATHS)

APPLICANT_CATEGORY_TEXT = "Органы государственной власти субъектов Российской Федерации"
APPLICANT_CATEGORY_MARKERS = (
    "Органы государственной власти",
    "государственной власти субъектов",
)
REFERENCE_VALIDATION_MARKERS = (
    "Не выбрано значение из справочника",
    "дозаполните сведения",
    "дозаполнить сведения",
    "Выберите значение из справочника",
    "дозаполните сведения о заявителе",
    "дозаполнить сведения о заявителе",
)


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


AUTHORITY_DOCUMENT_TYPE = "Иной документ"


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


MAX_FILE_ATTEMPTS = 5
MAX_SUBMIT_ERROR_RETRIES = 5
SUBMIT_REQUEST_ERROR_MARKERS = (
    "Не удалось отправить заявление",
    "Не удалось финализировать заявление",
    "Request failed with status code",
)
SUBMIT_SUCCESS_XPATH = "//div[text()='Ваша заявка отправлена в ведомство']"
SUBMIT_RESULT_TIMEOUT = 1500
SUBMIT_POLL_INTERVAL = 10
SUBMIT_PROCESSING_MARKERS = ("Идет процесс отправки документов",)
CERTIFICATE_OPTION_XPATH = "//span[@class='certificate-selector__list-option']"
VIPISKA_TEXT = (
    "Выписка из Единого государственного реестра недвижимости "
    "о переходе прав на объект недвижимости"
)
VIPISKA_MARKER = "Выписка из Единого государственного реестра"


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
    time.sleep(1)


def _click_vybrat_button(drv, stage="submit", timeout=15):
    btn = WebDriverWait(drv, timeout).until(
        EC.element_to_be_clickable(("xpath", "//button[text()='Выбрать']"))
    )
    drv.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", btn)
    log_info("Кнопка 'Выбрать' нажата, заявка отправляется", stage=stage)


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


def _modal_button_text_matches(text, action):
    normalized = (text or "").strip().upper()
    return normalized in {label.upper() for label in _MODAL_BUTTON_LABELS[action]}


def _find_modal_button(modal, action):
    for btn in modal.find_elements("xpath", ".//button"):
        if btn.is_displayed() and _modal_button_text_matches(btn.text, action):
            return btn
    return None


def _pick_react_select_input(inputs):
    """Выбирает рабочий input react-select (ID назначается динамически)."""
    if not inputs:
        return None
    for inp in inputs:
        if inp.is_enabled():
            return inp
    return inputs[0]


def _find_react_select_input_in(container, drv=None, timeout=15, visible_only=False):
    """Находит input react-select внутри контейнера (модалка или страница)."""

    def input_ready(_d):
        inputs = container.find_elements("xpath", _REACT_SELECT_INPUT_XPATH)
        if visible_only:
            inputs = [inp for inp in inputs if inp.is_displayed()]
        return _pick_react_select_input(inputs) or False

    if drv is not None and timeout:
        return WebDriverWait(drv, timeout).until(input_ready)
    result = input_ready(None)
    if not result:
        raise TimeoutException("react-select input не найден в контейнере")
    return result


def _modal_contains_applicant_residence(modal):
    if APPLICANT_RESIDENCE_MODAL_CONTENT_ID in (modal.get_attribute("id") or ""):
        return True
    return bool(
        modal.find_elements("xpath", f".//div[@id='{APPLICANT_RESIDENCE_MODAL_CONTENT_ID}']")
    )


def _applicant_residence_modal_visible(drv):
    return any(_modal_contains_applicant_residence(m) for m in _visible_address_modals(drv))


def _get_applicant_residence_modal(drv):
    modals = [m for m in _visible_address_modals(drv) if _modal_contains_applicant_residence(m)]
    return modals[-1] if modals else None


def _page_has_required_field_error(drv):
    for el in drv.find_elements(
        "xpath",
        "//span[contains(@class, 'rros-ui-lib-message--error') or contains(@class, 'error')]",
    ):
        if el.is_displayed() and "Заполните обязательное поле" in (el.text or ""):
            return True
    return False


def _modal_fias_fields_complete(modal):
    """ФИАС-адрес в модалке заполнен до улицы и дома (если они требуются)."""
    try:
        region = modal.find_element("xpath", ".//input[@id='input.region']")
        if not (region.get_attribute("value") or "").strip():
            return False

        street_inputs = modal.find_elements("xpath", ".//input[@id='input.street']")
        if not street_inputs:
            return True

        street_val = (street_inputs[0].get_attribute("value") or "").strip()
        street_type_selected = any(
            "Улица" in (el.text or "")
            for el in modal.find_elements("xpath", ".//div[contains(@class, 'single-value')]")
        )
        if street_type_selected and not street_val:
            return False

        house_inputs = modal.find_elements("xpath", ".//input[@id='input.house']")
        if house_inputs and not (house_inputs[0].get_attribute("value") or "").strip():
            return False
    except NoSuchElementException:
        return False
    return True


def is_applicant_residence_address_filled(drv):
    """Адрес места жительства представителя сохранён на форме."""
    section = f"//div[contains(@id, '{APPLICANT_PERSON_SECTION}')]"
    try:
        for el in drv.find_elements(
            "xpath",
            f"{section}//div[contains(@class, 'fias-address-select__address-text')]",
        ):
            if not el.is_displayed():
                continue
            cls = el.get_attribute("class") or ""
            text = (el.text or "").strip()
            if (
                "fias-address-select__address-text--req" not in cls
                and text
                and "Заполните адрес" not in text
                and len(text) > 15
            ):
                return True

        for el in drv.find_elements(
            "xpath",
            f"{section}//div[contains(@class, 'fias-address-select__btn-edit')]",
        ):
            if el.is_displayed():
                return True

        if _page_has_required_field_error(drv):
            return False
    except Exception:
        pass
    return False


def open_applicant_residence_address_modal(drv, stage="applicant_address"):
    """Открывает модалку адреса места жительства представителя."""
    if _get_applicant_residence_modal(drv) is not None:
        return True

    try:
        section = drv.find_element(
            "xpath", f"//div[contains(@id, '{APPLICANT_PERSON_SECTION}')]"
        )
        drv.execute_script("arguments[0].scrollIntoView({block: 'center'});", section)
        time.sleep(0.5)
    except NoSuchElementException:
        pass

    last_err = None
    for xpath in APPLICANT_RESIDENCE_OPEN_XPATHS:
        try:
            opener = WebDriverWait(drv, 8).until(
                EC.element_to_be_clickable(("xpath", xpath))
            )
            drv.execute_script(
                "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
                opener,
            )
            WebDriverWait(drv, 15).until(
                lambda d: _get_applicant_residence_modal(d) is not None
            )
            time.sleep(1)
            log_info(f"Модалка адреса заявителя открыта: {xpath}", stage=stage)
            return True
        except Exception as e:
            last_err = e
    raise last_err or TimeoutException("Не удалось открыть модалку адреса заявителя")


def _focus_address_control_in_modal(drv, modal, stage="address"):
    selectors = (
        ".//div[contains(@class, 'rros-ui-lib-dropdown__control')]",
        ".//div[contains(@class, 'rros-ui-lib-dropdown__value-container')]",
        ".//div[contains(@class, 'rros-ui-lib-dropdown__placeholder')]",
        ".//div[contains(text(), 'Начните вводить')]",
    )
    for sel in selectors:
        for el in modal.find_elements("xpath", sel):
            if el.is_displayed():
                drv.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
                    el,
                )
                time.sleep(0.8)
                log_info(f"Фокус на контроле адреса: {sel}", stage=stage)
                return el
    raise TimeoutException("Не найден видимый контрол react-select в модалке")


def _find_address_input_in_modal(drv, modal, timeout=15):
    return _find_react_select_input_in(modal, drv=drv, timeout=timeout)


def _type_address_in_modal(drv, modal, text, stage="address"):
    if _modal_fias_fields_complete(modal):
        log_info("Поля ФИАС в модалке уже заполнены, ввод пропущен", stage=stage)
        return _find_address_input_in_modal(drv, modal, timeout=5)

    if _address_has_visible_suggestions(drv):
        log_info("Подсказки адреса уже видны, ввод пропущен", stage=stage)
        return _find_address_input_in_modal(drv, modal, timeout=5)

    _focus_address_control_in_modal(drv, modal, stage=stage)

    try:
        input_el = _find_address_input_in_modal(drv, modal, timeout=10)
    except TimeoutException:
        log_warning("react-select input не найден, ввод через ActionChains", stage=stage)
        control = _focus_address_control_in_modal(drv, modal, stage=stage)
        ActionChains(drv).click(control).pause(0.3).send_keys(text).perform()
        time.sleep(1.5)
        return _find_address_input_in_modal(drv, modal, timeout=5)

    current = (input_el.get_attribute("value") or "").strip()
    if current and not _modal_fias_fields_complete(modal):
        _clear_address_input(drv, input_el)
        time.sleep(0.2)

    try:
        input_el.send_keys(text)
    except ElementNotInteractableException:
        control = _focus_address_control_in_modal(drv, modal, stage=stage)
        ActionChains(drv).click(control).pause(0.3).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).send_keys(Keys.DELETE).send_keys(text).perform()
    log_info("Адрес введён в модалке", stage=stage, value=text[:120])
    time.sleep(1.5)
    return _find_address_input_in_modal(drv, modal, timeout=5)


def _select_best_fias_option(drv, options, preferred_text=None):
    if not options:
        return None
    if not preferred_text:
        return options[0]

    preferred = preferred_text.lower()
    parts = [p.strip().lower() for p in preferred.split(",") if len(p.strip()) > 3]
    best = options[0]
    best_score = -1
    for opt in options:
        txt = (opt.text or "").strip()
        if not txt:
            continue
        lower = txt.lower()
        score = 0
        if preferred in lower or lower in preferred:
            score += 100
        score += sum(10 for part in parts if part in lower)
        score += min(len(txt) // 10, 20)
        if score > best_score:
            best_score = score
            best = opt
    return best


def _select_fias_suggestion_in_modal(drv, modal, preferred_text=None, stage="address"):
    for click_attempt in range(2):
        try:
            options = wait_fias_suggestions(drv, timeout=12 if click_attempt == 0 else 4)
            option = _select_best_fias_option(drv, options, preferred_text)
            if option is None:
                raise TimeoutException("Нет подходящих подсказок ФИАС")
            option_text = (option.text or "")[:200]
            drv.execute_script(
                "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
                option,
            )
            log_info(
                "Выбрана подсказка ФИАС",
                stage=stage,
                option_text=option_text,
                method="click",
            )
            time.sleep(1)
            return True
        except StaleElementReferenceException:
            if _modal_fias_fields_complete(modal):
                return True
        except TimeoutException:
            break

    try:
        fresh_input = _find_address_input_in_modal(drv, modal, timeout=5)
        fresh_input.send_keys(Keys.ENTER)
        log_info("Подсказка выбрана через Enter", stage=stage, method="enter")
        time.sleep(1)
        return True
    except Exception:
        return _modal_fias_fields_complete(modal)


def _wait_modal_address_fields(drv, modal, timeout=15):
    def fields_ready(d):
        return _modal_fias_fields_complete(modal)

    WebDriverWait(drv, timeout).until(fields_ready)


def _save_address_modal(drv, modal, stage="address", timeout=20):
    def save_ready(d):
        if not _modal_fias_fields_complete(modal):
            return False
        btn = _find_modal_button(modal, "save")
        return btn if btn and btn.is_enabled() else False

    save_button = WebDriverWait(drv, timeout).until(save_ready)
    drv.execute_script("arguments[0].scrollIntoView({block: 'center'});", save_button)
    drv.execute_script("arguments[0].click();", save_button)
    time.sleep(2)
    log_info("Кнопка «Сохранить» нажата в модалке адреса", stage=stage)
    return True


def ensure_applicant_residence_address(drv, stage="applicant_address"):
    """Заполняет и сохраняет адрес места жительства представителя."""
    if not MIN_ADDRESS:
        log_warning("MIN_ADDRESS не задан в config/.env", stage=stage)
        return False

    if is_applicant_residence_address_filled(drv):
        log_info("Адрес заявителя уже заполнен, пропуск", stage=stage)
        return True

    modal = _get_applicant_residence_modal(drv)
    if modal is None:
        try:
            open_applicant_residence_address_modal(drv, stage=stage)
        except Exception as e:
            if not (_page_has_required_field_error(drv) or _applicant_residence_modal_visible(drv)):
                log_warning("Модалка адреса заявителя не открылась", stage=stage, exc=e)
                return False
        modal = _get_applicant_residence_modal(drv)

    if modal is None:
        return False

    for attempt in range(2):
        try:
            if _modal_fias_fields_complete(modal) and _find_modal_button(modal, "save"):
                btn = _find_modal_button(modal, "save")
                if btn and btn.is_enabled():
                    _save_address_modal(drv, modal, stage=stage, timeout=10)
                    if is_applicant_residence_address_filled(drv):
                        log_info("Адрес заявителя сохранён", stage=stage)
                        return True

            _type_address_in_modal(
                drv, modal, MIN_ADDRESS, stage=stage,
            )
            _select_fias_suggestion_in_modal(
                drv, modal, preferred_text=MIN_ADDRESS, stage=stage,
            )
            _wait_modal_address_fields(drv, modal, timeout=15)
            _save_address_modal(drv, modal, stage=stage, timeout=20)

            if is_applicant_residence_address_filled(drv):
                log_info("Адрес заявителя сохранён и подтверждён", stage=stage)
                return True

            modal = _get_applicant_residence_modal(drv)
            if modal is None and not _page_has_required_field_error(drv):
                return True
        except Exception as e:
            log_warning(
                f"Попытка {attempt + 1}/2 заполнения адреса заявителя не удалась",
                stage=stage, exc=e,
            )
            modal = _get_applicant_residence_modal(drv)
            if modal is None:
                try:
                    open_applicant_residence_address_modal(drv, stage=stage)
                except Exception:
                    pass
                modal = _get_applicant_residence_modal(drv)

    if is_applicant_residence_address_filled(drv):
        return True
    log_warning("Не удалось сохранить адрес заявителя", stage=stage, driver=drv)
    modal = _get_applicant_residence_modal(drv)
    if modal is not None:
        btn = _find_modal_button(modal, "cancel")
        if btn is not None:
            drv.execute_script("arguments[0].click();", btn)
            time.sleep(0.5)
    return False


def open_object_address_modal(drv, stage="address"):
    """Открывает модалку адреса объекта; пробует несколько локаторов."""
    close_address_modals(drv, stage=stage)
    try:
        section = drv.find_element("css selector", REAL_ESTATE_SECTION)
        drv.execute_script("arguments[0].scrollIntoView({block: 'center'});", section)
        time.sleep(0.5)
    except NoSuchElementException:
        pass

    last_err = None
    for xpath in OBJECT_ADDRESS_OPEN_XPATHS:
        try:
            address_menu = WebDriverWait(drv, 8).until(
                EC.element_to_be_clickable(("xpath", xpath))
            )
            drv.execute_script(
                "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
                address_menu,
            )
            WebDriverWait(drv, 15).until(
                lambda d: any(
                    m.find_elements("xpath", _REACT_SELECT_INPUT_XPATH)
                    for m in _visible_address_modals(d)
                )
            )
            ensure_single_address_modal(drv, stage=stage)
            time.sleep(2)
            log_info(f"Модалка адреса открыта: {xpath}", stage=stage)
            return True
        except Exception as e:
            last_err = e
    raise last_err or TimeoutException("Не удалось открыть модалку адреса")


def ensure_single_address_modal(drv, stage="address"):
    """Оставляет ровно одну модалку; лишние закрывает через ОТМЕНА."""
    modals = _visible_address_modals(drv)
    while len(modals) > 1:
        for modal in modals[:-1]:
            btn = _find_modal_button(modal, "cancel")
            if btn is not None:
                drv.execute_script("arguments[0].click();", btn)
                time.sleep(0.5)
                break
        modals = _visible_address_modals(drv)
        if len(modals) > 1:
            ActionChains(drv).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.5)
            modals = _visible_address_modals(drv)
        if len(modals) > 1:
            close_address_modals(drv, stage=stage)
            break


def focus_address_select_control(drv, stage="address"):
    """Клик по видимому контролу react-select в активной модалке."""
    ensure_single_address_modal(drv, stage=stage)
    modal = _active_address_modal(drv)
    if modal is None:
        raise TimeoutException("Модалка адреса не открыта")

    selectors = (
        ".//div[contains(@class, 'rros-ui-lib-dropdown__control')]",
        ".//div[contains(@class, 'rros-ui-lib-dropdown__value-container')]",
        ".//div[contains(@class, 'rros-ui-lib-dropdown__placeholder')]",
        ".//div[contains(text(), 'Начните вводить')]",
    )
    for sel in selectors:
        for el in modal.find_elements("xpath", sel):
            if el.is_displayed():
                drv.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
                    el,
                )
                time.sleep(0.8)
                log_info(f"Фокус на контроле адреса: {sel}", stage=stage)
                return el
    raise TimeoutException("Не найден видимый контрол react-select в модалке")


def wait_address_input_visible(drv, timeout=15):
    """Ждёт, пока input react-select станет видимым — тогда send_keys работает."""

    def visible(d):
        for modal in reversed(_visible_address_modals(d)):
            for inp in modal.find_elements("xpath", _REACT_SELECT_INPUT_XPATH):
                if inp.is_displayed():
                    return inp
        for inp in d.find_elements(
            "xpath", "//input[starts-with(@id, 'react-select-') and contains(@id, '-input')]"
        ):
            if inp.is_displayed():
                return inp
        return False

    return WebDriverWait(drv, timeout).until(visible)


def _clear_address_input(drv, input_el):
    try:
        input_el.send_keys(Keys.CONTROL, "a")
        input_el.send_keys(Keys.DELETE)
    except Exception:
        try:
            ActionChains(drv).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform()
        except Exception:
            drv.execute_script("arguments[0].focus(); arguments[0].value = '';", input_el)


def _address_has_visible_suggestions(drv):
    for xpath in ADDRESS_OPTION_XPATHS:
        opts = [
            o for o in drv.find_elements("xpath", xpath)
            if o.is_displayed() and (o.text or "").strip()
        ]
        if opts:
            return True
    return False


def type_address_for_fias_autocomplete(drv, text, stage="address"):
    """
    Ввод адреса — один проход. Если текст уже в поле или подсказки видны — не перепечатывать.
    """
    modal = _active_address_modal(drv)
    if modal is not None and _modal_fias_fields_complete(modal):
        for el in modal.find_elements("xpath", ".//div[contains(@class, 'single-value')]"):
            shown = (el.text or "").strip()
            if len(shown) > 10 and "Начните вводить" not in shown:
                log_info("Адрес уже отображается в контроле, ввод пропущен", stage=stage, value_after=shown[:100])
                return find_address_input(drv, timeout=5)

    focus_address_select_control(drv, stage=stage)

    if _address_has_visible_suggestions(drv):
        log_info("Подсказки адреса уже видны, ввод пропущен", stage=stage)
        return find_address_input(drv, timeout=5)

    try:
        input_el = find_address_input(drv, timeout=5)
        current = (input_el.get_attribute("value") or "").strip()
        if len(current) >= 5:
            log_info("Адрес уже в поле, повторный ввод не нужен", stage=stage, value_after=current[:100])
            return input_el
    except Exception:
        input_el = None

    # 1) visible input + send_keys
    try:
        input_el = wait_address_input_visible(drv, timeout=8)
        current = (input_el.get_attribute("value") or "").strip()
        if len(current) < 5:
            _clear_address_input(drv, input_el)
            input_el.send_keys(text)
            time.sleep(1.5)
        value = (input_el.get_attribute("value") or "")[:200]
        if len(value) >= 5 or _address_has_visible_suggestions(drv):
            log_info("Адрес введён (visible input)", stage=stage, value_after=value)
            return input_el
    except TimeoutException:
        log_warning("Input не стал visible, пробуем ActionChains на контроле", stage=stage)
    except ElementNotInteractableException as e:
        log_warning("send_keys на visible input не сработал", stage=stage, exc=e)

    if _address_has_visible_suggestions(drv):
        return find_address_input(drv, timeout=5)

    # 2) ActionChains на контроле (один раз, с очисткой)
    control = focus_address_select_control(drv, stage=stage)
    ActionChains(drv).click(control).pause(0.3).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).send_keys(Keys.DELETE).send_keys(text).perform()
    time.sleep(1.5)

    input_el = find_address_input(drv, timeout=5)
    value = (input_el.get_attribute("value") or "")[:200]
    if len(value) >= 5 or _address_has_visible_suggestions(drv):
        log_info("Адрес введён (ActionChains на контроле)", stage=stage, value_after=value)
        return input_el

    log_warning("Адрес не введён после двух попыток", stage=stage, value_after=value)
    return input_el


def is_address_filled_on_form(drv):
    """Адрес объекта (realEstateItems) уже сохранён на форме."""
    try:
        edit_btns = drv.find_elements(
            "css selector", f"{REAL_ESTATE_SECTION} .fias-address-select__btn-edit"
        )
        if any(b.is_displayed() for b in edit_btns):
            return True

        for el in drv.find_elements(
            "css selector", f"{REAL_ESTATE_SECTION} .fias-address-select__address-text"
        ):
            if not el.is_displayed():
                continue
            cls = el.get_attribute("class") or ""
            text = (el.text or "").strip()
            if (
                "fias-address-select__address-text--req" not in cls
                and text
                and "Заполните адрес" not in text
                and len(text) > 20
            ):
                return True

        fill_btns = drv.find_elements(
            "css selector", f"{REAL_ESTATE_SECTION} .fias-address-select__btn-filling"
        )
        if any(b.is_displayed() for b in fill_btns):
            return False

        if not _visible_address_modals(drv):
            prompts = drv.find_elements(
                "xpath", "//div[@id='realEstateItems']//div[text()='Заполните адрес']"
            )
            return not any(p.is_displayed() for p in prompts)
    except Exception:
        pass
    return False


def wait_modal_address_fields(drv, timeout=15):
    """Ждёт заполнения полей ФИАС в модалке после выбора подсказки."""
    modal = _active_address_modal(drv)

    def fields_ready(d):
        if modal is not None:
            return _modal_fias_fields_complete(modal)
        try:
            region = d.find_element(
                "xpath", f"{ADDRESS_MODAL_XPATH}//input[@id='input.region']"
            )
            return bool((region.get_attribute("value") or "").strip())
        except NoSuchElementException:
            return False

    WebDriverWait(drv, timeout).until(fields_ready)


def is_modal_address_ready_to_save(drv):
    """В модалке адрес распознан ФИАС и кнопка «Сохранить» активна."""
    modal = _active_address_modal(drv)
    if modal is None:
        return False
    if not _modal_fias_fields_complete(modal):
        return False
    btn = _find_modal_button(modal, "save")
    return bool(btn and btn.is_enabled())


def try_save_modal_address(drv, stage="address"):
    """Пытается сохранить уже заполненный адрес в открытой модалке."""
    if not is_modal_address_ready_to_save(drv):
        return False
    try:
        save_button = wait_address_save_button(drv, timeout=5)
        drv.execute_script("arguments[0].click();", save_button)
        time.sleep(3)
        if is_address_filled_on_form(drv):
            log_info("Адрес сохранён из модального окна", stage=stage)
            return True
    except Exception as e:
        log_warning("Не удалось сохранить адрес из модалки", stage=stage, exc=e)
    return False


def _visible_address_modals(drv):
    return [
        m for m in drv.find_elements("xpath", ADDRESS_MODAL_XPATH)
        if m.is_displayed()
    ]


def _active_address_modal(drv):
    modals = _visible_address_modals(drv)
    if not modals:
        return None
    for modal in reversed(modals):
        if not _modal_contains_applicant_residence(modal):
            return modal
    return modals[-1]


def close_address_modals(drv, stage="address"):
    """Закрывает все зависшие модальные окна адреса перед новой попыткой."""
    for _ in range(4):
        modals = _visible_address_modals(drv)
        if not modals:
            return True

        for modal in _visible_address_modals(drv):
            btn = _find_modal_button(modal, "cancel")
            if btn is not None:
                drv.execute_script("arguments[0].click();", btn)
                time.sleep(0.5)

        ActionChains(drv).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.8)

    remaining = len(_visible_address_modals(drv))
    if remaining:
        log_warning(
            f"После закрытия осталось модальных окон: {remaining}",
            stage=stage, driver=drv,
        )
    return remaining == 0


def reopen_address_modal(drv, stage="address"):
    open_object_address_modal(drv, stage=stage)


def find_address_input(drv, timeout=15):
    """Поле react-select в активной модалке (часто скрыто, opacity:0)."""

    def input_ready(d):
        modal = _active_address_modal(d)
        if modal is not None:
            picked = _pick_react_select_input(
                modal.find_elements("xpath", _REACT_SELECT_INPUT_XPATH)
            )
            if picked is not None:
                return picked
        for m in reversed(_visible_address_modals(d)):
            picked = _pick_react_select_input(
                m.find_elements("xpath", _REACT_SELECT_INPUT_XPATH)
            )
            if picked is not None:
                return picked
        return False

    return WebDriverWait(drv, timeout).until(input_ready)


def wait_fias_suggestions(drv, timeout=12):
    def suggestions_ready(d):
        for xpath in ADDRESS_OPTION_XPATHS:
            opts = [
                o for o in d.find_elements("xpath", xpath)
                if o.is_displayed() and (o.text or "").strip()
            ]
            if opts:
                return opts
        return False

    return WebDriverWait(drv, timeout).until(suggestions_ready)


def select_fias_address_suggestion(drv, address_input, preferred_text=None):
    """Клик по подсказке ФИАС; не используем ARROW_DOWN — он попадает в поле «Квартира»."""
    for click_attempt in range(2):
        try:
            options = wait_fias_suggestions(drv, timeout=12 if click_attempt == 0 else 4)
            option = _select_best_fias_option(drv, options, preferred_text)
            if option is None:
                raise TimeoutException("Нет подходящих подсказок ФИАС")
            option_text = (option.text or "")[:200]
            drv.execute_script(
                "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
                option,
            )
            log_info(
                "Выбрана подсказка ФИАС",
                stage="address",
                option_text=option_text,
                method="click",
            )
            time.sleep(1)
            return True
        except StaleElementReferenceException:
            log_info(
                "DOM обновился после клика по подсказке — проверяем заполнение формы",
                stage="address",
            )
            if is_modal_address_ready_to_save(drv):
                return True
        except TimeoutException:
            break

    try:
        fresh_input = find_address_input(drv, timeout=5)
        fresh_input.send_keys(Keys.ENTER)
        log_info("Подсказка выбрана через Enter", stage="address", method="enter")
        time.sleep(1)
        return True
    except Exception:
        return is_modal_address_ready_to_save(drv)


def wait_address_save_button(drv, timeout=20):
    def save_ready(d):
        modal = _active_address_modal(d)
        if modal is not None:
            btn = _find_modal_button(modal, "save")
            if btn and btn.is_enabled():
                return btn
        for modal in _visible_address_modals(d):
            btn = _find_modal_button(modal, "save")
            if btn and btn.is_enabled():
                return btn
        return False

    return WebDriverWait(drv, timeout).until(save_ready)


def select_address_ultimate():
    stage = "address"
    max_attempts = 2

    if is_address_filled_on_form(driver):
        close_address_modals(driver, stage=stage)
        log_info("Адрес уже заполнен на форме — ввод не требуется", stage=stage)
        return True

    for attempt in range(max_attempts):
        try:
            log_info(
                f"Попытка {attempt + 1}/{max_attempts} заполнения адреса",
                stage=stage, address=MIN_ADDRESS,
                address_state=collect_address_state(driver),
            )

            if is_address_filled_on_form(driver):
                close_address_modals(driver, stage=stage)
                log_info("Адрес заполнен во время попытки", stage=stage)
                return True

            if attempt > 0:
                log_info("Переоткрытие модального окна адреса", stage=stage)
                close_address_modals(driver, stage=stage)
                reopen_address_modal(driver, stage=stage)
            else:
                log_info("Ожидание полного открытия модального окна", stage=stage)
                if _visible_address_modals(driver):
                    close_address_modals(driver, stage=stage)
                open_object_address_modal(driver, stage=stage)
                time.sleep(1)

            container = type_address_for_fias_autocomplete(driver, MIN_ADDRESS, stage=stage)
            log_info(
                f"Поле адреса после ввода",
                stage=stage,
                field_value=(container.get_attribute("value") or "")[:100],
                displayed=container.is_displayed(),
            )

            suggestions_found = False
            try:
                wait_fias_suggestions(driver, timeout=15)
                suggestions_found = True
            except TimeoutException:
                pass

            addr_after_input = collect_address_state(driver)
            value_after = (container.get_attribute("value") or "")[:200]
            log_info(
                "Состояние после ввода адреса",
                stage=stage,
                value_after=value_after,
                dropdown_options=addr_after_input.get("dropdown_options_count"),
                react_select_options=addr_after_input.get("react_select_options_count"),
                suggestions_found=suggestions_found,
            )

            options_total = (
                addr_after_input.get("dropdown_options_count", 0)
                + addr_after_input.get("react_select_options_count", 0)
            )
            if not suggestions_found and options_total == 0:
                log_scenario(
                    "address_no_dropdown_options", stage, driver=driver, screenshot=True,
                    message="После ввода адреса не появились варианты в выпадающем списке ФИАС",
                    attempt=attempt + 1,
                    typed_address=MIN_ADDRESS,
                    value_after=value_after,
                    recommendation="Подсказки ФИАС не загрузились — проверьте сеть или текст адреса.",
                )
                continue

            select_fias_address_suggestion(driver, container, preferred_text=MIN_ADDRESS)

            try:
                wait_modal_address_fields(driver, timeout=15)
            except TimeoutException:
                log_warning(
                    "Поля ФИАС в модалке не заполнились после выбора подсказки",
                    stage=stage, driver=driver,
                )

            if is_address_filled_on_form(driver):
                close_address_modals(driver, stage=stage)
                log_info("Адрес объекта уже на форме после выбора подсказки", stage=stage)
                return True

            addr_after_select = collect_address_state(driver)
            log_info(
                "Состояние после выбора из списка",
                stage=stage,
                selected_values=addr_after_select.get("selected_values"),
            )

            try:
                save_button = wait_address_save_button(driver, timeout=20)
            except TimeoutException as e:
                log_scenario(
                    "address_save_button_not_found", stage, driver=driver, exc=e,
                    screenshot=True,
                    message="Кнопка «Сохранить» не стала активной в модальном окне адреса",
                    attempt=attempt + 1,
                )
                continue

            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", save_button)
            driver.execute_script("arguments[0].click();", save_button)
            time.sleep(3)

            addr_final = collect_address_state(driver)
            if not is_address_filled_on_form(driver) and addr_final.get("fill_address_prompt_visible"):
                if try_save_modal_address(driver, stage=stage):
                    return True
                log_scenario(
                    "address_not_saved", stage, driver=driver, screenshot=True,
                    message="После нажатия «Сохранить» по-прежнему отображается «Заполните адрес»",
                    attempt=attempt + 1,
                    address_state=addr_final,
                )
                continue

            log_info(
                "Адрес сохранён и подтверждён",
                stage=stage, address=MIN_ADDRESS,
                selected_values=addr_final.get("selected_values"),
            )
            return True

        except Exception as e:
            if is_address_filled_on_form(driver):
                close_address_modals(driver, stage=stage)
                log_info("Адрес уже сохранён на форме (после ошибки)", stage=stage)
                return True
            if try_save_modal_address(driver, stage=stage):
                close_address_modals(driver, stage=stage)
                log_info("Адрес сохранён после восстановления из модалки", stage=stage)
                return True

            log_scenario(
                "address_attempt_failed", stage, driver=driver, exc=e,
                screenshot=(attempt == max_attempts - 1),
                message=f"Ошибка на попытке {attempt + 1} заполнения адреса",
                attempt=attempt + 1,
            )
            if attempt < max_attempts - 1:
                log_info("Повторная попытка заполнения адреса", stage=stage)
                time.sleep(2)
            else:
                log_scenario(
                    "address_all_attempts_failed", stage, driver=driver, screenshot=True,
                    message="Все попытки заполнения адреса исчерпаны",
                )

    return is_address_filled_on_form(driver)


def is_page_loaded(driver):
    try:
        return driver.execute_script("return document.readyState") == "complete"
    except Exception as e:
        log_warning("Не удалось проверить readyState страницы", stage="page_load", exc=e)
        return False

def is_modal_loaded():
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


def wait_for_all_loadings():
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


login_funct(driver)

#driver.set_window_size(300, 300) 

# Основной цикл обработки CSV файлов
for upload_file in uploads_file_dir.iterdir():
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

            form_ready = False

            if not file_ctx["page_loaded"]:
                if not is_page_loaded(driver):
                    log_warning("Страница не загружена полностью, ожидание readyState", stage=stage, driver=driver)
                    try:
                        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                    except Exception as e:
                        log_exception(stage, e, driver=driver, message="Таймаут ожидания загрузки страницы")

                try:
                    driver.get("https://lk.rosreestr.ru/eservices/request-info-from-egrn/real-estate-object-or-its-rightholder")
                    log_info("Переход на страницу поиска по ЕГРН", stage="applicant_category", file=upload_file.name)
                    time.sleep(10)
                    file_ctx["page_loaded"] = True
                except Exception as e:
                    on_file_failure("не удалось открыть страницу формы", exc=e)
                    continue
            else:
                log_info(
                    "Страница уже открыта, повторная загрузка не требуется",
                    stage=stage, file=upload_file.name,
                )
                close_address_modals(driver, stage="address")

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
                        if select_address_ultimate():
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
                    driver.find_element("xpath", "(//input[@type='file'])[1]").send_keys(file_path)
                    time.sleep(5)
                    log_info(f"Загружен PDF: {PDF_FILE_NAME}", stage="file_upload")

                    driver.find_element("tag name", "body").click()
                    time.sleep(1)

                    driver.find_element("xpath", "(//input[@type='file'])[2]").send_keys(file_signature)
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

log_info("Скрипт завершён", stage="shutdown")
try:
    write_session_report()
except Exception as e:
    log_warning("Не удалось записать итоговый отчёт сессии", stage="shutdown", exc=e)
try:
    driver.quit()
except Exception as e:
    log_warning("Ошибка при закрытии WebDriver", stage="shutdown", exc=e)



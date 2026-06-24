
"""Логирование, диагностика и запись results.log."""
import atexit
import json
import logging
import sys
import time
import traceback
from datetime import datetime

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)

from .config import DIAGNOSTICS_DIR, LOG_DIR, RESULTS_LOG, SCREENSHOTS_DIR
from .constants import ADDRESS_MODAL_XPATH, ADDRESS_SAVE_XPATH, _REACT_SELECT_INPUT_XPATH
from .constants import CSV_UPLOAD_ERROR_XPATHS

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



def save_selenium_note(driver, message, screenshot=False):
    """Сохраняет заметку для Selenium с возможностью скриншота"""
    note_file = RESULTS_LOG
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

  from .csv_upload import collect_csv_upload_state as _collect_csv
  diag["csv_upload"] = _collect_csv(driver)
  from .address import collect_address_state as _collect_addr
  diag["address"] = _collect_addr(driver)

  return diag


def log_scenario(scenario, stage, driver=None, message=None, exc=None, screenshot=False, **context):
  """Именованный сценарий ошибки с полной диагностикой CSV/адреса."""
  if driver is not None:
    if stage == "csv_upload" or scenario.startswith("csv_"):
      fp = context.pop("file_path", None)
      from .csv_upload import collect_csv_upload_state
      context["csv_state"] = collect_csv_upload_state(driver, fp)
      if fp is not None:
        context["file"] = fp.name if hasattr(fp, "name") else str(fp)
    if stage == "address" or scenario.startswith("address_"):
      from .address import collect_address_state
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

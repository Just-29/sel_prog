"""XPath, маркеры и таймауты для автоматизации Росреестра."""

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

AUTHORITY_DOCUMENT_TYPE = "Иной документ"

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

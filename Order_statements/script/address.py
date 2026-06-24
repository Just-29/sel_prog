
"""Адрес объекта и адрес заявителя (ФИАС)."""
import time

from selenium.common.exceptions import (
    ElementNotInteractableException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .constants import (
    ADDRESS_MODAL_XPATH,
    ADDRESS_OPTION_XPATHS,
    ADDRESS_SAVE_XPATH,
    APPLICANT_PERSON_SECTION,
    APPLICANT_RESIDENCE_MODAL_CONTENT_ID,
    APPLICANT_RESIDENCE_OPEN_XPATHS,
    OBJECT_ADDRESS_OPEN_XPATHS,
    REAL_ESTATE_SECTION,
    _MODAL_BUTTON_LABELS,
    _REACT_SELECT_INPUT_XPATH,
)
from .config import MIN_ADDRESS
from .logging_utils import log_info, log_scenario, log_warning


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


def select_address_ultimate(driver):
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

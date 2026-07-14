
"""Создание и настройка WebDriver."""
import os
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait

from .config import CHROME_PATH, CHROME_PROFILE_PATH, DRIVER_PATH, WEBDRIVER_WAIT_TIMEOUT
from .logging_utils import log_error, log_info, log_warning

# Окно за экраном: Selenium видит нормальный layout, пользователь не мешает.
_BACKGROUND_WINDOW_SIZE = (1920, 1080)
_BACKGROUND_WINDOW_POS = (-32000, -32000)


def kill_chrome_processes():
    log_info("Завершение процессов Chrome/chromedriver перед запуском", stage="init")
    os.system("taskkill /f /im chrome.exe 2>nul")
    os.system("taskkill /f /im chromedriver.exe 2>nul")
    time.sleep(2)


def _background_enabled() -> bool:
    return os.getenv("BROWSER_BACKGROUND", "true").lower() not in ("0", "false", "no")


def _move_browser_offscreen(driver) -> None:
    """Уводит окно за экран без headless — расширения и нативные диалоги остаются рабочими."""
    width, height = _BACKGROUND_WINDOW_SIZE
    x, y = _BACKGROUND_WINDOW_POS
    try:
        driver.set_window_rect(x=x, y=y, width=width, height=height)
    except Exception as e:
        try:
            driver.set_window_size(width, height)
            driver.set_window_position(x, y)
        except Exception as e2:
            log_warning(
                "Не удалось увести окно браузера в фон",
                stage="init",
                exc=e2 or e,
            )
            return
    log_info(
        "Браузер запущен в фоне (окно за экраном)",
        stage="init",
        window=f"{width}x{height} @ {x},{y}",
    )


def create_driver():
    os.environ["WDM_LOG_LEVEL"] = "0"

    chrome_options = Options()
    chrome_options.binary_location = CHROME_PATH
    chrome_options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
    chrome_options.add_argument("--profile-directory=Default")
    chrome_options.add_argument("--log-level=0")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    chrome_options.set_capability(
        "goog:loggingPrefs", {"browser": "ALL", "driver": "WARNING"}
    )

    # Не используем --headless: ломает расширения Госуслуг и окна Госплагин/КриптоПро.
    # Фон = окно за экраном с нормальным размером (элементы остаются interactable).
    if _background_enabled():
        width, height = _BACKGROUND_WINDOW_SIZE
        x, y = _BACKGROUND_WINDOW_POS
        chrome_options.add_argument(f"--window-size={width},{height}")
        chrome_options.add_argument(f"--window-position={x},{y}")

    service = Service(executable_path=DRIVER_PATH, log_path="NUL")
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        log_error("Не удалось запустить WebDriver", stage="init", exc=e, screenshot=False)
        raise
    log_info("WebDriver успешно запущен", stage="init", chrome_path=CHROME_PATH)

    if _background_enabled():
        _move_browser_offscreen(driver)

    wait = WebDriverWait(driver, WEBDRIVER_WAIT_TIMEOUT, poll_frequency=1)
    actions = ActionChains(driver)
    return driver, wait, actions

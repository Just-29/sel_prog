
"""Создание и настройка WebDriver."""
import os
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait

from .config import CHROME_PATH, CHROME_PROFILE_PATH, DRIVER_PATH, WEBDRIVER_WAIT_TIMEOUT
from .logging_utils import log_error, log_info


def kill_chrome_processes():
    log_info("Завершение процессов Chrome/chromedriver перед запуском", stage="init")
    os.system("taskkill /f /im chrome.exe 2>nul")
    os.system("taskkill /f /im chromedriver.exe 2>nul")
    time.sleep(2)


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

    service = Service(executable_path=DRIVER_PATH, log_path="NUL")
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        log_error("Не удалось запустить WebDriver", stage="init", exc=e, screenshot=False)
        raise
    log_info("WebDriver успешно запущен", stage="init", chrome_path=CHROME_PATH)
    wait = WebDriverWait(driver, WEBDRIVER_WAIT_TIMEOUT, poll_frequency=1)
    actions = ActionChains(driver)
    return driver, wait, actions

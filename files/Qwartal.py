import os
import time

from datetime import datetime
from pathlib import Path
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver import Keys

from config import *


# Закрываем все процессы Chrome перед запуском
os.system('taskkill /f /im chrome.exe 2>nul')
os.system('taskkill /f /im chromedriver.exe 2>nul')
time.sleep(2)

# Отключаем логи только webdriver-manager
os.environ['WDM_LOG_LEVEL'] = '0'

chrome_options = Options()
chrome_options.binary_location = CHROME_PATH

# Путь к профилю с установленными расширениями
chrome_options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
chrome_options.add_argument("--profile-directory=Default")

# Отключение логов
chrome_options.add_argument("--log-level=0")
chrome_options.add_argument("--disable-logging")
chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])

service = Service(
    executable_path=DRIVER_PATH,
    log_path='NUL'  # Перенаправляем логи ChromeDriver в никуда
)

driver = webdriver.Chrome(service=service, options=chrome_options)

wait = WebDriverWait(driver, 300, poll_frequency=1)

script_dir = Path(__file__).parent
file_path = os.path.join(script_dir, "uploads", PDF_FILE_NAME)
file_signature = os.path.join(script_dir, "uploads", SIGNATURE_FILE_NAME)
uploads_file_dir = script_dir / "uploads" / "qwartal_files.txt"

def save_selenium_note(driver, message, screenshot=False):
    """Сохраняет заметку для Selenium с возможностью скриншота"""
    notes_dir = Path(__file__).parent / "selenium_notes"
    notes_dir.mkdir(exist_ok=True)
    
    note_file = notes_dir / "qwartal.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(note_file, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {message}\n")

def login_funct(driver):
    wait = WebDriverWait(driver, 5)
    driver.get("https://lk.rosreestr.ru/my-applications")
    try:
        if wait.until(EC.visibility_of_element_located(("xpath", "//button[text()=' Восстановить ']"))):
            wait.until(EC.visibility_of_element_located(("xpath", "//button[text()=' Эл. подпись ']"))).click()
            print("\n", "\t", "нажата кнопка электронной подписи")
            time.sleep(5)
            wait.until(EC.visibility_of_element_located(("xpath", "//button[text()=' Продолжить ']"))).click()
            print("\n", "\t", "нажата кнопка продолжить")
            time.sleep(5)
            wait.until(EC.visibility_of_element_located(("xpath", "//button[contains(., 'МИНИСТЕРСТВО ЖИЛИЩНО-КОММУНАЛЬНОГО ХОЗЯЙСТВА')]"))).click()
            print("\n", "\t", "МИНИСТЕРСТВО ЖКХ")
            time.sleep(10)
            wait.until(EC.visibility_of_element_located(("xpath", "//span[text()='МИНИСТЕРСТВО ЖИЛИЩНО-КОММУНАЛЬНОГО ХОЗЯЙСТВА, ТОПЛИВА И ЭНЕРГЕТИКИ РЕСПУБЛИКИ СЕВЕРНАЯ ОСЕТИЯ-АЛАНИЯ']"))).click()
            print("\n", "\t", "выбран пользователь")
            time.sleep(5)
    except:
        driver.get("https://lk.rosreestr.ru/my-applications")
        print("\n", "\t", "переход на страницу росреестра")
        wait.until(EC.visibility_of_element_located(("xpath", "//span[text()='МИНИСТЕРСТВО ЖИЛИЩНО-КОММУНАЛЬНОГО ХОЗЯЙСТВА, ТОПЛИВА И ЭНЕРГЕТИКИ РЕСПУБЛИКИ СЕВЕРНАЯ ОСЕТИЯ-АЛАНИЯ']"))).click()
        print("\n", "\t", "выбран пользователь")
        time.sleep(5)

login_funct(driver)

# При обработке файлов из директории qwartal_files
txt_file = script_dir / "uploads" / "qwartal_files.txt"
if txt_file.is_file():
    with open(txt_file, 'r', encoding='utf-8') as file:
        lines = [line.strip() for line in file if line.strip() and not line.strip().startswith('#')]
        for line in lines:

            print(f"📄 Обработка строки {line}")

            driver.get("https://lk.rosreestr.ru/eservices/request-info-from-egrn/cpt")
            print("\n", "\t", "переход на страницу поиска по ЕГРН")
            time.sleep(10)

            # Выбор категории
            scroll_category = driver.find_element("xpath", "//input[@id='applicantCategory']")
            scroll_category.send_keys("Иные определенные федеральным законом")
            time.sleep(1)
            scroll_category.send_keys(Keys.ARROW_DOWN)
            time.sleep(1)
            scroll_category.send_keys(Keys.ENTER)
            time.sleep(1)

            # Ввод даты
            driver.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].regDate']").send_keys(DOCUMENT_DATE)
            print("\n", "\t", "ввод даты")

            # Ввод email (фиксирован)
            
            driver.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].email']").clear()
            driver.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].email']").send_keys(QWART_EMAIL)
            driver.find_element("xpath", "//input[@id='fullNameDocumentAndAdditionalInformationArray[0].email']").clear()
            driver.find_element("xpath", "//input[@id='fullNameDocumentAndAdditionalInformationArray[0].email']").send_keys(QWART_EMAIL)
            print("ввод email")
            time.sleep(1)

            # Фиксированный адрес — React Select
            element = driver.find_element("xpath", "(//div[text()='Заполните адрес'])[1]")
            driver.execute_script("arguments[0].click();", element)
            print("\n", "\t", "открытие меню адреса")
            time.sleep(5)

            react_input = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located(("xpath", "//input[@id='react-select-3-input']"))
            )
            react_input.send_keys(MIN_ADDRESS) 
            time.sleep(3)
            react_input.send_keys(Keys.ARROW_DOWN)
            time.sleep(2)
            react_input.send_keys(Keys.ENTER)
            print("нашел необходимый адрес")
            time.sleep(2)

            driver.find_element("xpath", "(//button[text()='Сохранить'])[1]").click()
            print("сохранен адресс")
            time.sleep(2)

            # Ввод остальных данных (документы, файлы)
            driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentType']").send_keys("Иной документ")
            time.sleep(1)
            print("ввел текст")
            driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentType']").send_keys(Keys.ARROW_DOWN)
            print("стрелка вниз")
            time.sleep(1)
            driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentType']").send_keys(Keys.ENTER)
            print("энтер")
            time.sleep(1)
            driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentNumber']").send_keys("583-p")
            time.sleep(1)
            print("ввел номер документа")
            driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentIssueDate']").send_keys("23.12.2024")
            time.sleep(1)
            print("ввел дату выдачи документа")
            driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.issuingAuthority']").send_keys(ISSUING_AUTHORITY)
            time.sleep(1)
            print("\t ввел кем выдан")

            driver.find_element("xpath", "(//input[@type='file'])[1]").send_keys(file_path)
            time.sleep(15)
            print("отправил 1")
            driver.find_element("xpath", "(//input[@type='file'])[2]").send_keys(file_signature)
            time.sleep(15)
            print("отправил 2")

            # Ввод cadastralBlockNumber из текущей строки файла
            driver.find_element("xpath", "//input[@id='cadastralBlockNumber']").clear()
            driver.find_element("xpath", "//input[@id='cadastralBlockNumber']").send_keys(line)
            print("отправил кадастрr")
            time.sleep(1)

            # Отправка email и другие действия
            driver.find_element("xpath", "//input[@id='deliveryActionEmail']").clear()
            driver.find_element("xpath", "//input[@id='deliveryActionEmail']").send_keys(QWART_EMAIL)
            print("email")
            time.sleep(1)

            # Кнопки Далее и дальнейшие действия
            BUTTON_FURTHER = ("xpath", "//button[text()='Далее']")
            wait.until(EC.element_to_be_clickable(BUTTON_FURTHER)).click()
            time.sleep(5)
            print("первая Далее")
            wait.until(EC.visibility_of_element_located(BUTTON_FURTHER))
            time.sleep(5)
            wait.until(EC.visibility_of_element_located(BUTTON_FURTHER)).click()
            time.sleep(2)
            print("вторая Далее")
            wait.until(EC.visibility_of_element_located(("xpath", "//span[@class='certificate-selector__list-option']"))).click()
            print("выбрал")
            time.sleep(1)
            wait.until(EC.visibility_of_element_located(("xpath", "//button[text()='Выбрать']"))).click()
            print("финальная далее")
            wait.until(EC.visibility_of_element_located(("xpath", "//div[text()='Ваша заявка отправлена в ведомство']")))
            save_selenium_note(driver, line)
            time.sleep(10)

print("end code")
driver.quit()
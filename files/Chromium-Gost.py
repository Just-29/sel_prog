import os
import time

from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException
from datetime import datetime
from pathlib import Path
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver import Keys
from selenium.webdriver.common.action_chains import ActionChains

from config import *

# //div[@class='rros-ui-lib-errors'] див ошибок
# //button[@class='rros-ui-lib-button rros-ui-lib-button--link'] крестик для закрытия сообщений об ошибке
# Закрываем все процессы Chrome перед запуском
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


service = Service(
    executable_path=DRIVER_PATH,
    log_path='NUL'  # Перенаправляем логи ChromeDriver в никуда
)

driver = webdriver.Chrome(service=service, options=chrome_options)

wait = WebDriverWait(driver, 1000, poll_frequency=1)


script_dir = Path(__file__).parent
file_path = os.path.join(script_dir, "uploads", PDF_FILE_NAME)
file_signature = os.path.join(script_dir, "uploads", SIGNATURE_FILE_NAME)
uploads_file_dir = script_dir / "uploads" / "uploads_files"

actions = ActionChains(driver)

def wait_for_file_upload_by_title(driver, file_path):
    try:
        # Загружаем файл
        driver.find_element("xpath", "(//input[@type='file'])[3]").send_keys(str(file_path))
        
        # Ждем подтверждения загрузки файла
        wait.until(
            EC.presence_of_element_located(("xpath", 
                f"//span[contains(@title, '{file_path.name}') and contains(@class, 'rros-ui-lib-file-upload__item__name')]"))
        )
        print(f"✅ Файл {file_path.name} успешно загружен")
        time.sleep(2)

        apply_button_xpath = "//button[contains(@class, 'my-objects-modal__selected-btn') and contains(@class, 'rros-ui-lib-button--primary') and text()='Применить']"
        
        print("⏳ Ожидаем появления кнопки 'Применить'...")
        
        try:
            wait.until(EC.presence_of_element_located(("xpath", "//h3[text()='Поиск среди загруженных объектов недвижимости']")))
            confirm_button = wait.until(
                EC.element_to_be_clickable(("xpath", apply_button_xpath))
            )
            print("✅ Кнопка 'Применить' найдена и кликабельна")
            
            # Нажимаем кнопку через JavaScript
            driver.execute_script("arguments[0].click();", confirm_button)
            print("✅ Кнопка 'Применить' нажата через JavaScript")
            
            # Ждем ЗАКРЫТИЯ модального окна - это ключевой момент
            print("⏳ Ожидаем закрытия модального окна...")
            try:
                # Ждем исчезновения модального окна
                wait.until(EC.invisibility_of_element_located(("xpath", "//div[contains(@class, 'rros-ui-lib-modal__window')]")))
                print("✅ Модальное окно успешно закрыто")
                return False  # Успех
                
            except Exception as e:
                print(f"⚠️ Модальное окно не закрылось автоматически: {e}")
                
                # Пробуем закрыть модальное окно вручную
                print("🔄 Пробуем закрыть модальное окно вручную...")
                if close_modal_window(driver):
                    print("✅ Модальное окно закрыто вручную")
                    return False  # Успех
                else:
                    print("❌ Не удалось закрыть модальное окно")
                    return True  # Продолжаем цикл
                
        except Exception as e:
            print(f"❌ Не удалось найти или нажать кнопку 'Применить': {e}")
            return True

    except Exception as e:
        print(f"❌ Общая ошибка при загрузке файла: {e}")
        return True

def close_modal_window(driver):
    """Закрывает мешающие модальные окна"""
    try:
        # Пробуем разные способы закрытия
        
        # Способ 1: Крестик закрытия
        close_buttons = driver.find_elements("xpath", "//button[contains(@class, 'rros-ui-lib-modal__close-btn')]")
        if close_buttons:
            driver.execute_script("arguments[0].click();", close_buttons[0])
            print("✅ Модальное окно закрыто через крестик")
            time.sleep(2)
            return True
            
        # Способ 2: Кнопка "Отмена" или "Закрыть"
        cancel_buttons = driver.find_elements("xpath", "//button[contains(text(), 'Отмена') or contains(text(), 'Закрыть') or contains(text(), 'Cancel')]")
        if cancel_buttons:
            driver.execute_script("arguments[0].click();", cancel_buttons[0])
            print("✅ Модальное окно закрыто через кнопку отмены")
            time.sleep(2)
            return True
            
        # Способ 3: ESC через JavaScript
        driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', {'key': 'Escape'}));")
        print("✅ Отправлен ESC через JavaScript")
        time.sleep(2)
        
        # Проверяем закрылось ли окно
        if not driver.find_elements("xpath", "//div[contains(@class, 'rros-ui-lib-modal__window')]"):
            return True
        else:
            print("⚠️ ESC не сработал")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка при закрытии модального окна: {e}")
        return False



def save_selenium_note(driver, message, screenshot=False):
    """Сохраняет заметку для Selenium с возможностью скриншота"""
    notes_dir = Path(__file__).parent / "selenium_notes"
    notes_dir.mkdir(exist_ok=True)
    
    # Текстовая заметка
    note_file = notes_dir / "actions.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(note_file, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {message}\n")

def login_funct(driver):
    wait = WebDriverWait(driver, 15)
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

def select_address_ultimate():
    try:
        print("Запуск надежного выбора адреса...")
        
        # Через ActionChains
        container = wait.until(EC.element_to_be_clickable(
            ("xpath", "//input[@id='react-select-3-input']")
        ))
        container.click()
        time.sleep(1)
        
        hidden_input = driver.find_element("id", "react-select-3-input")
        
        # Очистка и ввод
        hidden_input.send_keys(Keys.CONTROL + "a")
        time.sleep(1)
        hidden_input.send_keys(Keys.DELETE)
        time.sleep(1)
        hidden_input.send_keys(MIN_ADDRESS)
        time.sleep(2)
        
        # Надежная последовательность стрелок и Enter
        actions = ActionChains(driver)
        actions.send_keys(Keys.ARROW_DOWN)
        actions.pause(1)
        actions.send_keys(Keys.ENTER)
        actions.perform()
        
        print("✓ Действия выполнены: СтрелкаВниз + Enter")
        time.sleep(1)
        wait.until(EC.element_to_be_clickable(("xpath", "(//button[text()='Сохранить'])[1]"))).click()
        print('Адрес министерства сохранен')        
        time.sleep(2)
        return True
        
    except Exception as e:
        print(f"✗ Ошибка в основном методе: {e}")
        return False


login_funct(driver)

#driver.set_window_size(300, 300) 

# Основной цикл обработки CSV файлов
for upload_file in uploads_file_dir.iterdir():
    flag_download_CSV_file = False
    while flag_download_CSV_file == False:

        if upload_file.is_file() and upload_file.suffix.lower() == '.csv':
            print(f"\n📁 Обработка файла: {upload_file.name}")

            driver.get("https://lk.rosreestr.ru/eservices/request-info-from-egrn/real-estate-object-or-its-rightholder")
            print("\n", "\t", "переход на страницу поиска по ЕГРН")
            time.sleep(10)
            wait.until(EC.presence_of_element_located(("xpath", "//input[@id='applicantCategory']")))
            scroll_category = driver.find_element("xpath", "//input[@id='applicantCategory']")
            driver.execute_script("arguments[0].click();", scroll_category)
            scroll_category.send_keys("Органы государственной власти субъектов Российской Федерации")
            time.sleep(1)
            print("ввел иные...")
            scroll_category.send_keys(Keys.ARROW_DOWN)
            time.sleep(1)
            print("отправил стрелку")
            scroll_category.send_keys(Keys.ENTER)
            time.sleep(1)
            print("отправил энтер")

            print("dropdown 1")
            time.sleep(0.3)
            driver.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].regDate']").send_keys(DOCUMENT_DATE)
            print("\n", "\t", "ввод даты")

            driver.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].email']").clear()
            driver.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].email']").send_keys(EMAIL)
            driver.find_element("xpath", "//input[@id='fullNameDocumentAndAdditionalInformationArray[0].email']").clear()
            driver.find_element("xpath", "//input[@id='fullNameDocumentAndAdditionalInformationArray[0].email']").send_keys(EMAIL)
            driver.find_element("xpath", "//input[@id='requestAboutObject.deliveryActionEmail']").clear()
            driver.find_element("xpath", "//input[@id='requestAboutObject.deliveryActionEmail']").send_keys(EMAIL)
            print("ввод email")
            time.sleep(1)
            print("выбор типа документа")


            try:
                address_menu = wait.until(EC.element_to_be_clickable(("xpath", "(//div[text()='Заполните адрес'])[1]")))
                driver.execute_script("arguments[0].click();", address_menu)
                time.sleep(1)
                if select_address_ultimate():
                    print("✓ Адрес успешно выбран!")
                else:
                    print("✗ Не удалось выбрать адрес")
                    driver.save_screenshot('address_error.png')
                    exit(1)

            except Exception as e:
                print(f"✗ Критическая ошибка: {e}")
                driver.save_screenshot('critical_error.png')
                exit(1)

            time.sleep(2)

            
            # Первое поле: ввод текста и выбор из выпадающего списка
            element1 = driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentType']")
            actions.click(element1).send_keys("Иной документ").pause(1)
            actions.send_keys(Keys.ARROW_DOWN).pause(1)
            actions.send_keys(Keys.ENTER).pause(1)

            # Второе поле: номер документа
            element2 = driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentNumber']")
            actions.click(element2).send_keys(DOCUMENT_NUMBER).pause(1)

            # Третье поле: дата выдачи документа
            element3 = driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentIssueDate']")
            actions.click(element3).send_keys(DOCUMENT_DATE).pause(1)

            # Четвертое поле: кем выдан
            element4 = driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.issuingAuthority']")
            actions.click(element4).send_keys(ISSUING_AUTHORITY).pause(1)

            # Textarea: добавляем клик и ввод текста
            textarea = driver.find_element("xpath", "//textarea[@name='groundsForDataFurnishing']")
            actions.click(textarea).send_keys(CORRECTION).pause(1)
            actions.perform()
            print("Все поля заполнены через ActionChains")
            time.sleep(1)

            vipiska_container = driver.find_element("xpath", "//input[@id='react-select-6-input']")

            vipiska_container.send_keys("Выписка из Единого государственного реестра недвижимости о переходе прав на объект недвижимости")
            print('прописал тип выписки')
            time.sleep(2)

            # Надежная последовательность стрелок и Enter
            actions.send_keys(Keys.ARROW_DOWN)
            print('прожал стрелку вниз на типе выписки')
            actions.pause(1)
            actions.send_keys(Keys.ENTER)
            print('прожал enter на тип выписки')
            actions.perform()
            time.sleep(1)


            # файл
            driver.find_element("xpath", "(//input[@type='file'])[1]").send_keys(file_path)
            time.sleep(15)
            print("отправил 1")
            # файл
            driver.find_element("xpath", "(//input[@type='file'])[2]").send_keys(file_signature)
            time.sleep(15)
            print("отправил 2")

            # файл csv
            loading_flag = True
            attempt = 0
            max_attempts = 5

            while loading_flag and attempt < max_attempts:
                attempt += 1
                print(f"🔄 Попытка загрузки CSV {attempt}/{max_attempts}")

                # Загружаем файл
                loading_flag = wait_for_file_upload_by_title(driver, upload_file)

                # Если функция вернула True (неудача), обрабатываем очистку
                if loading_flag:
                    print("🔄 Очищаем и пробуем снова...")

                    # ЖДЕМ появления кнопки удаления с использованием глобального wait
                    try:
                        print("⏳ Ожидаем появления кнопки 'Удалить'...")
                        delete_button = wait.until(
                            EC.element_to_be_clickable(("xpath", "//button[contains(@class, 'csv-control__btn-del') and contains(., 'Удалить')]"))
                        )
                        delete_button.click()
                        print("✅ Кнопка 'Удалить' нажата")

                        # Ждем пока файл удалится (исчезнет элемент с именем файла)
                        try:
                            wait.until(EC.invisibility_of_element_located(("xpath", 
                                f"//span[contains(@title, '{upload_file.name}') and contains(@class, 'rros-ui-lib-file-upload__item__name')]")))
                            print("✅ Файл успешно удален из интерфейса")
                        except:
                            print("⚠️ Файл не исчез из интерфейса, но продолжаем...")

                    except Exception as e:
                        print(f"⚠️ Не удалось найти или нажать кнопку 'Удалить': {e}")

                    if loading_flag and attempt < max_attempts:
                        print("🔄 Повторная попытка через 3 секунды...")
                        time.sleep(3)


                else:
                    # Пауза перед следующей попыткой
                    if loading_flag and attempt < max_attempts:
                        print("🔄 Повторная попытка через 3 секунды...")
                        time.sleep(3)


            try:
                wait.until(EC.presence_of_element_located(("xpath", "//div[text()='Добавлено объектов из CSV-файла:']")))
                print("✅ CSV-файл найден, продолжаем работу")

            except:
                print("❌ CSV-файл не появился в течение 300 секунд")

        time.sleep(2)

        BUTTON_FURTHER = ("xpath", "//button[text()='Далее']")
        wait.until(EC.element_to_be_clickable(BUTTON_FURTHER)).click()
        time.sleep(5)
        print("первая Далее")
        wait.until(EC.visibility_of_element_located(BUTTON_FURTHER))
        time.sleep(5)
        wait.until(EC.element_to_be_clickable(BUTTON_FURTHER)).click()
        time.sleep(2)
        print("вторая Далее")
        wait.until(EC.visibility_of_element_located(("xpath", "//span[@class='certificate-selector__list-option']"))).click()
        print("выбрал")
        time.sleep(1)
        wait.until(EC.visibility_of_element_located(("xpath", "//button[text()='Выбрать']"))).click()
        print("финальная далее")
        try:
            wait.until(EC.visibility_of_element_located(("xpath", "//div[text()='Ваша заявка отправлена в ведомство']")))
            save_selenium_note(driver, f"УСПЕХ✌: Файл {upload_file} отправлен")
            flag_download_CSV_file = True
            time.sleep(10)
        except Exception as e:
            save_selenium_note(driver, f"ОШИБКА💥: Файл {upload_file} не отправлен - {type(e).__name__}: {str(e)}")
            time.sleep(10)
    
print("end code")
driver.quit()


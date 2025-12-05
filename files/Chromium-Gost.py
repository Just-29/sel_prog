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

from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException, ElementNotInteractableException
import traceback

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

wait = WebDriverWait(driver, 1500, poll_frequency=1)


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
    driver.get("https://lk.rosreestr.ru/eservices/request-info-from-egrn/real-estate-object-or-its-rightholder")
    try:
        if wait.until(EC.presence_of_element_located(("xpath", "//h1[contains(.,'Не удается получить доступ к сайту')]"))):
            driver.get("https://lk.rosreestr.ru/eservices/request-info-from-egrn/real-estate-object-or-its-rightholder")
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
        driver.get("https://lk.rosreestr.ru/eservices/request-info-from-egrn/real-estate-object-or-its-rightholder")
        print("\n", "\t", "переход на страницу росреестра")
        wait.until(EC.visibility_of_element_located(("xpath", "//span[text()='МИНИСТЕРСТВО ЖИЛИЩНО-КОММУНАЛЬНОГО ХОЗЯЙСТВА, ТОПЛИВА И ЭНЕРГЕТИКИ РЕСПУБЛИКИ СЕВЕРНАЯ ОСЕТИЯ-АЛАНИЯ']"))).click()
        print("\n", "\t", "выбран пользователь")
        time.sleep(5)

def close_modal_windows():
    """Функция для закрытия мешающих модальных окон"""
    try:
        # Пробуем ESC
        actions = ActionChains(driver)
        actions.send_keys(Keys.ESCAPE).perform()
        time.sleep(1)
        
        # Ищем кнопки закрытия модальных окон
        close_selectors = [
            "//button[contains(@class, 'close')]",
            "//button[contains(@class, 'modal-close')]",
            "//div[contains(@class, 'overlay')]",
            "//button[text()='Закрыть']",
            "//button[text()='Отмена']"
        ]
        
        for selector in close_selectors:
            try:
                close_btn = driver.find_elements("xpath", selector)
                if close_btn:
                    driver.execute_script("arguments[0].click();", close_btn[0])
                    print(f"✓ Закрыто модальное окно через {selector}")
                    time.sleep(1)
            except:
                continue
                
    except Exception as e:
        print(f"⚠️ Не удалось закрыть модальные окна: {e}")


def select_address_ultimate():
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            print(f"Попытка {attempt + 1} заполнения адреса...")
            
            # Даем больше времени на анимацию открытия модального окна
            print("Ожидание полного открытия модального окна...")
            time.sleep(5)
            
            # Пробуем найти активное поле ввода
            container = None
            selectors = [
                "//input[@id='react-select-3-input']",
                "//input[contains(@id, 'react-select')]",
                "//input[contains(@placeholder, 'адрес')]",
                "//div[contains(@class, 'select')]//input"
            ]
            
            for selector in selectors:
                try:
                    # Ждем пока элемент станет кликабельным
                    container = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable(("xpath", selector))
                    )
                    print(f"✓ Найден и доступен элемент через: {selector}")
                    break
                except:
                    continue
            
            if not container:
                print("✗ Не удалось найти доступное поле ввода адреса")
                # Пробуем обновить модальное окно
                try:
                    print("Пробуем переоткрыть модальное окно...")
                    actions = ActionChains(driver)
                    actions.send_keys(Keys.ESCAPE).perform()
                    time.sleep(2)
                    
                    # Снова открываем модальное окно
                    address_menu = wait.until(EC.element_to_be_clickable(("xpath", "(//div[text()='Заполните адрес'])[1]")))
                    driver.execute_script("arguments[0].click();", address_menu)
                    time.sleep(3)
                    continue
                except:
                    continue
            
            # Пробуем разные способы активации поля
            try:
                # Способ 1: JavaScript клик (самый надежный)
                driver.execute_script("arguments[0].click();", container)
                print("✓ JavaScript клик выполнен")
            except:
                try:
                    # Способ 2: ActionChains с перемещением
                    actions = ActionChains(driver)
                    actions.move_to_element(container).click().perform()
                    print("✓ ActionChains клик выполнен")
                except:
                    try:
                        # Способ 3: Простой клик
                        container.click()
                        print("✓ Обычный клик выполнен")
                    except Exception as click_error:
                        print(f"✗ Все способы клика не сработали: {click_error}")
                        continue
            
            time.sleep(2)
            
            # Проверяем что поле стало активным
            if not container.is_enabled():
                print("⚠️ Поле осталось неактивным после клика")
                continue
            
            # Очистка и ввод адреса
            print(f"Ввод адреса: {MIN_ADDRESS}")
            
            # Очищаем поле
            container.send_keys(Keys.CONTROL + "a")
            time.sleep(0.5)
            container.send_keys(Keys.DELETE)
            time.sleep(0.5)
            
            # Вводим адрес
            container.send_keys(MIN_ADDRESS)
            time.sleep(3)  # Ждем появления вариантов
            
            # Выбор из списка
            container.send_keys(Keys.ARROW_DOWN)
            time.sleep(1)
            container.send_keys(Keys.ENTER)
            time.sleep(2)
            
            # Сохранение
            save_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(("xpath", "(//button[text()='Сохранить'])[1]"))
            )
            driver.execute_script("arguments[0].click();", save_button)
            time.sleep(4)
            
            print("✓ Адрес сохранен")
            return True
                    
        except Exception as e:
            print(f"✗ Ошибка на попытке {attempt + 1}: {e}")
            if attempt < max_attempts - 1:
                print("Пробуем снова...")
                time.sleep(3)
            else:
                print("❌ Все попытки исчерпаны")
                driver.save_screenshot(f'address_final_error_{int(time.time())}.png')
    
    return False


def is_page_loaded(driver):
    try:
        return driver.execute_script("return document.readyState") == "complete"
    except:
        return False

def is_modal_loaded():
    """Проверка что модальное окно полностью загружено"""
    try:
        # Проверяем что модальное окно видимо
        modal_visible = EC.visibility_of_element_located((
            "xpath", "//div[contains(@class, 'modal')] | //div[contains(@class, 'rros-ui-lib-modal')]"
        ))
        # Проверяем что поле ввода доступно
        input_ready = EC.element_to_be_clickable(("xpath", "//input[@id='react-select-3-input']"))
        
        return modal_visible(driver) and input_ready(driver)
    except:
        return False


def wait_for_all_loadings():
    """Ожидание исчезновения всех loading-индикаторов"""
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
            print(f"✓ Loading исчез: {selector}")
        except:
            print(f"⚠️ Loading не найден или не исчез: {selector}")
    
    time.sleep(1)


login_funct(driver)

#driver.set_window_size(300, 300) 

# Основной цикл обработки CSV файлов
for upload_file in uploads_file_dir.iterdir():
    flag_download_CSV_file = False
    while flag_download_CSV_file == False:

        if upload_file.is_file() and upload_file.suffix.lower() == '.csv':
            print(f"\n📁 Обработка файла: {upload_file.name}")

            # Проверка загрузки страницы
            if not is_page_loaded(driver):
                print("⚠️ Страница не загружена полностью, ждем...")
                wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")

            try:
                driver.get("https://lk.rosreestr.ru/eservices/request-info-from-egrn/real-estate-object-or-its-rightholder")
                print("\n", "\t", "переход на страницу поиска по ЕГРН")
                time.sleep(10)

                # Ждем появления элемента с детальной обработкой ошибок
                try:
                    wait.until(EC.presence_of_element_located(("xpath", "//input[@id='applicantCategory']")))
                    print("✓ Элемент applicantCategory найден")
                except TimeoutException:
                    print("✗ Таймаут: элемент applicantCategory не появился за отведенное время")
                    # Проверим что вообще загрузилось на странице
                    page_source = driver.page_source
                    if "applicantCategory" in page_source:
                        print("⚠️ Элемент есть в DOM, но не видим")
                    else:
                        print("⚠️ Элемента нет в DOM")
                    continue
                
                # Находим элемент
                try:
                    scroll_category = driver.find_element("xpath", "//input[@id='applicantCategory']")
                    print("✓ Элемент успешно найден через find_element")
                except NoSuchElementException:
                    print("✗ Элемент не найден через find_element")
                    # Попробуем альтернативные локаторы
                    alternative_locators = [
                        "//input[contains(@id, 'applicant')]",
                        "//input[contains(@class, 'applicant')]",
                        "//*[contains(text(), 'Органы государственной')]",
                        "//select[@id='applicantCategory']"
                    ]
                    for locator in alternative_locators:
                        try:
                            scroll_category = driver.find_element("xpath", locator)
                            print(f"✓ Найден через альтернативный локатор: {locator}")
                            break
                        except NoSuchElementException:
                            continue
                    else:
                        print("Не удалось найти элемент ни одним из способов")
                        continue

                # Клик через JavaScript с обработкой ошибок
                try:
                    driver.execute_script("arguments[0].click();", scroll_category)
                    print("✓ JavaScript клик выполнен")
                except Exception as e:
                    print(f"✗ Ошибка JavaScript клика: {e}")
                    # Пробуем обычный клик
                    try:
                        scroll_category.click()
                        print("✓ Обычный клик выполнен")
                    except Exception as e2:
                        print(f"✗ Ошибка обычного клика: {e2}")
                        continue
                    
                # Ввод текста
                try:
                    scroll_category.send_keys("Органы государственной власти субъектов Российской Федерации")
                    print("✓ Текст введен успешно")
                except ElementNotInteractableException:
                    print("✗ Элемент не доступен для ввода")
                    # Проверим видимость и доступность
                    is_displayed = scroll_category.is_displayed()
                    is_enabled = scroll_category.is_enabled()
                    print(f"Элемент displayed: {is_displayed}, enabled: {is_enabled}")
                    continue
                
                time.sleep(1)
                print("ввел иные...")

                # Стрелка вниз
                try:
                    scroll_category.send_keys(Keys.ARROW_DOWN)
                    print("✓ Стрелка вниз отправлена")
                except Exception as e:
                    print(f"✗ Ошибка отправки стрелки: {e}")

                time.sleep(1)
                print("отправил стрелку")

                # Enter
                try:
                    scroll_category.send_keys(Keys.ENTER)
                    print("✓ Enter отправлен")
                except Exception as e:
                    print(f"✗ Ошибка отправки Enter: {e}")

                time.sleep(1)
                print("отправил энтер")

            except TimeoutException as e:
                print(f"✗ Таймаут операции: {e}")
                print(f"Текущий URL: {driver.current_url}")
                print(f"Заголовок страницы: {driver.title}")
                driver.save_screenshot('error_timeout_ОрганыГосВласти.png')

            except NoSuchElementException as e:
                print(f"✗ Элемент не найден: {e}")
                print(f"Страница загружена: {driver.current_url}")
                driver.save_screenshot('error_no_element_ОрганыГосВласти.png')

            except ElementClickInterceptedException as e:
                print(f"✗ Клик перехвачен другим элементом: {e}")
                driver.save_screenshot('error_click_intercepted_ОрганыГосВласти.png')

            except ElementNotInteractableException as e:
                print(f"✗ Элемент не доступен для взаимодействия: {e}")
                driver.save_screenshot('error_not_interactable_ОрганыГосВласти.png')

            except Exception as e:
                print(f"✗ Критическая ошибка: {e}")
                print("Полная трассировка ошибки:")
                traceback.print_exc()
                print(f"Текущий URL: {driver.current_url}")
                print(f"Размер окна: {driver.get_window_size()}")
                driver.save_screenshot('error_critical_ОрганыГосВласти.png')

                # Дополнительная диагностика
                try:
                    page_title = driver.title
                    page_source_length = len(driver.page_source)
                    print(f"Диагностика - Title: {page_title}, Source length: {page_source_length}")
                except:
                    print("Не удалось получить диагностическую информацию")

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

                    # Улучшенная проверка доступности формы
                    try:
                        # Ждем когда форма станет полностью доступной
                        WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable(("xpath", "//body"))
                        )
                        # Кликаем на body чтобы убедиться что нет перекрывающих элементов
                        driver.execute_script("arguments[0].click();", driver.find_element("xpath", "//body"))
                        print("✓ Форма доступна для взаимодействия")
                    except Exception as e:
                        print(f"⚠️ Форма все еще заблокирована: {e}")
                        # Не прерываем выполнение, просто предупреждаем

                else:
                    print("✗ Не удалось выбрать адрес")
                    print("⚠️ Пробуем повторить...")
                    time.sleep(3)

                    # Повторная попытка
                    try:
                        address_menu = wait.until(EC.element_to_be_clickable(("xpath", "(//div[text()='Заполните адрес'])[1]")))
                        driver.execute_script("arguments[0].click();", address_menu)
                        time.sleep(1)

                        if select_address_ultimate():
                            print("✓ Адрес успешно выбран после повторной попытки!")
                        else:
                            print("✗ Критическая ошибка с адресом после двух попыток")
                            driver.save_screenshot('address_final_error.png')
                            continue

                    except Exception as retry_error:
                        print(f"✗ Ошибка при повторной попытке: {retry_error}")
                        driver.save_screenshot('address_retry_error.png')
                        continue

            except Exception as e:
                print(f"✗ Критическая ошибка при открытии модального окна: {e}")
                driver.save_screenshot('critical_error.png')
                continue

            time.sleep(2)


            
            # Документ, подтверждающий полномочия уполномоченного лица
            try:
                # Поле типа документа - клик через JavaScript
                element1 = driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentType']")
                
                # Вместо обычного клика используем JavaScript
                driver.execute_script("arguments[0].click();", element1)
                time.sleep(2)
                
                # После клика появляется выпадающий список, выбираем вариант
                driver.execute_script("arguments[0].value = 'Иной документ';", element1)
                time.sleep(1)
                
                # Или альтернативный способ - отправляем клавиши
                element1.send_keys("Иной документ")
                time.sleep(1)
                element1.send_keys(Keys.ARROW_DOWN)
                time.sleep(1)
                element1.send_keys(Keys.ENTER)
                time.sleep(2)
                print("✓ Тип документа заполнен")
            
                # Остальные поля
                element2 = driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentNumber']")
                element2.send_keys(DOCUMENT_NUMBER)
                time.sleep(1)
            
                element3 = driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.documentIssueDate']")
                element3.send_keys(DOCUMENT_DATE)
                time.sleep(1)
            
                element4 = driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.issuingAuthority']")
                element4.send_keys(ISSUING_AUTHORITY)
                time.sleep(1)
            
                textarea = driver.find_element("xpath", "//textarea[@name='groundsForDataFurnishing']")
                textarea.send_keys(CORRECTION)
                time.sleep(1)
                
                print("✓ Все поля документа заполнены")
                
            except Exception as e:
                print(f"✗ Ошибка при заполнении документов: {e}")
                driver.save_screenshot('document_error.png')
                continue
            
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
            try:
                driver.find_element("xpath", "(//input[@type='file'])[1]").send_keys(file_path)
                time.sleep(15)
                print("отправил 1")
                # файл
                driver.find_element("xpath", "(//input[@type='file'])[2]").send_keys(file_signature)
                time.sleep(15)
                print("отправил 2")
            except Exception as e:
                print(f"✗ Ошибка при отправке файлов: {e}")
                driver.save_screenshot("no_name_error.png")
                continue

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

        button_further = wait.until(EC.presence_of_element_located(("xpath", "//button[text()='Далее']")))
        BUTTON_FURTHER = ("xpath", "//button[text()='Далее']")
        try:
            driver.execute_script("arguments[0].click();", button_further)
            print("✓ Первая кнопка 'Далее' нажата через JavaScript")
            time.sleep(5)
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
        except Exception as e:
            print(f'✗ Критическая ошибка на этапе заполнения документов: {e}')
            print(f'Тип ошибки: {type(e).__name__}')

            # Делаем скриншот с временной меткой
            timestamp = int(time.time())
            driver.save_screenshot('button_further_error.png')
            print(f'Скриншот сохранен: button_further_error_{timestamp}.png')

            # Дополнительная диагностика
            try:
                current_url = driver.current_url
                page_title = driver.title
                print(f'Текущий URL: {current_url}')
                print(f'Заголовок страницы: {page_title}')
                continue
            except Exception as diag_error:
                print(f'Ошибка диагностики: {diag_error}')
                continue
            
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


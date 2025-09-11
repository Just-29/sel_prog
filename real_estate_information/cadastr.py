import os
import time
import json
import sys

from datetime import datetime
from pathlib import Path
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (TimeoutException, NoSuchElementException, 
                                      InvalidSessionIdException, WebDriverException)

# Отключаем логи только webdriver-manager
os.environ['WDM_LOG_LEVEL'] = '0'



def login_funct(driver): # функция входа в ЕГРН
    wait = WebDriverWait(driver, 10)
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
            driver.get("https://lk.rosreestr.ru/eservices/real-estate-objects-online")
    except:
        pass

    try:
        if wait.until(EC.visibility_of_element_located(("xpath", "//span[text()='МИНИСТЕРСТВО ЖИЛИЩНО-КОММУНАЛЬНОГО ХОЗЯЙСТВА, ТОПЛИВА И ЭНЕРГЕТИКИ РЕСПУБЛИКИ СЕВЕРНАЯ ОСЕТИЯ-АЛАНИЯ']"))):
            wait.until(EC.visibility_of_element_located(("xpath", "//span[text()='МИНИСТЕРСТВО ЖИЛИЩНО-КОММУНАЛЬНОГО ХОЗЯЙСТВА, ТОПЛИВА И ЭНЕРГЕТИКИ РЕСПУБЛИКИ СЕВЕРНАЯ ОСЕТИЯ-АЛАНИЯ']"))).click()
            print("\n", "\t", "выбран пользователь")
            time.sleep(5)
            driver.get("https://lk.rosreestr.ru/eservices/real-estate-objects-online")
    except:
        pass

def initialize_driver():

    """Инициализация драйвера с обработкой ошибок"""
    chrome_options = Options()
    chrome_options.binary_location = r"C:\Users\David\AppData\Local\Chromium\Application\chrome.exe"

    # Путь к профилю, с установленными расширениями
    chrome_options.add_argument(r"--user-data-dir=C:\Users\David\AppData\Local\Chromium\User Data")
    chrome_options.add_argument("--profile-directory=Default")

    # Отключение логов
    chrome_options.add_argument("--log-level=0")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    #chrome_options.add_argument("--headless")

    try:
        # Указываем конкретную версию ChromeDriver совместимую с Chrome 139
        service = Service(
            ChromeDriverManager(driver_version="139.0.7211.0").install(),
            log_path='NUL'  # Перенаправляем логи ChromeDriver в никуда
        )
        
        driver = webdriver.Chrome(service=service, options=chrome_options)
        wait = WebDriverWait(driver, 20, poll_frequency=1)
        return driver, wait
        
    except Exception as e:
        print(f"Ошибка инициализации драйвера: {e}")
        return None, None

def restart_driver(current_driver):
    """Перезапуск драйвера при ошибках соединения"""
    try:
        if current_driver:
            current_driver.quit()
    except:
        pass
    
    return initialize_driver()

def safe_send_keys(driver_ref, wait_ref, upload_address, max_retries=3):
    """Безопасный ввод адреса с обработкой ошибок и перезапуском драйвера"""
    for attempt in range(max_retries):
        try:
            # Обновляем страницу перед каждой попыткой
            driver_ref.get("https://lk.rosreestr.ru/eservices/real-estate-objects-online")
            
            # Ждем элемент и вводим текст
            input_element = wait_ref.until(
                EC.visibility_of_element_located(("xpath", "//input[@id='query']"))
            )
            input_element.clear()
            input_element.send_keys(upload_address.strip())
            return True, driver_ref, wait_ref
        
        except (TimeoutException, NoSuchElementException) as e:
            print(f"Попытка {attempt + 1}: Элемент не найден, обновляем страницу: {e}")
            time.sleep(2)
            
        except (InvalidSessionIdException, WebDriverException) as e:
            print(f"Попытка {attempt + 1}: Ошибка сессии, перезапускаем драйвер: {e}")
            driver_ref, wait_ref = restart_driver(driver_ref)
            if driver_ref is None:
                print("Не удалось перезапустить драйвер")
                return False, None, None
            time.sleep(5)
            
        except Exception as e:
            print(f"Попытка {attempt + 1}: Неожиданная ошибка: {e}")
            time.sleep(2)
    
    print(f"Не удалось ввести адрес после {max_retries} попыток: {upload_address}")
    return False, driver_ref, wait_ref

# Основной код
driver, wait = initialize_driver()
if driver is None:
    print("Не удалось инициализировать драйвер")
    exit()

# Дирректории для загрузок
script_dir = Path(__file__).parent
uploads_file_dir = script_dir / "address_uploads"

# Дирректория для заметки
notes_dir = Path(__file__).parent / "cadastr_result"
notes_dir.mkdir(exist_ok=True)

# JSON файл для результатов
note_file = notes_dir / "result.json"

# Загружаем существующие результаты или создаем новый словарь
if note_file.exists():
    try:
        with open(note_file, 'r', encoding='utf-8') as f:
            all_results = json.load(f)
        print(f"Загружены существующие результаты: {len(all_results)} адресов")
    except Exception as e:
        print(f"Ошибка загрузки файла, начинаем заново: {e}")
        all_results = {}
else:
    all_results = {}
    print("Файл результатов не найден, начинаем новый")

try:
    # Заходим на сайт
    driver.get("https://lk.rosreestr.ru/my-applications")
    print("\n", "\t", "переход на страницу росреестра")
    login_funct(driver)

    # Счетчик адресов
    address_count = 0
    new_addresses_count = 0  # Счетчик новых обработанных адресов

    # Проходим по всем файлам в папке address_uploads
    for upload_file in uploads_file_dir.iterdir():
        if upload_file.is_file():
            # Читаем адреса из файла
            try:
                with open(upload_file, 'r', encoding='utf-8') as f:
                    addresses = f.read().splitlines()
            except Exception as e:
                print(f"Ошибка чтения файла {upload_file}: {e}")
                continue

            # Проходим по каждому адресу из файла
            for upload_address in addresses:
                if not upload_address.strip():  # Пропускаем пустые строки
                    continue
                
                address_count += 1
                
                # Пропускаем уже обработанные адреса
                if upload_address in all_results:
                    print(f"Пропускаем уже обработанный адрес {address_count}: {upload_address}")
                    continue
                
                print(f"Обрабатываем новый адрес {address_count}: {upload_address}")
                new_addresses_count += 1
                    
                # Ввод адреса с обработкой ошибок
                success, driver, wait = safe_send_keys(driver, wait, upload_address)
                if not success:
                    login_funct(driver)
                    success, driver, wait = safe_send_keys(driver, wait, upload_address)
                    if not success:
                        # Если не удалось ввести адрес, сохраняем ошибку и продолжаем
                        all_results[upload_address] = {"error": "Не удалось ввести адрес, ошибка драйвера"}
                        continue
                
                time.sleep(5)
                
                # Клик по кнопке поиска с обработкой ошибок
                try:
                    # Кликаем по кнопке поиска
                    driver.find_element("xpath", "//button[@id='realestateobjects-search']").click()
                    time.sleep(3)

                    # Проверяем наличие ошибки БЕЗ выброса исключения
                    error_elements = driver.find_elements("xpath", "//*[contains(text(), 'Не удалось получить список объектов недвижимости')]")

                    if error_elements:  # Если найдены элементы с ошибкой
                        print("Обнаружена ошибка на сайте, обновляем страницу...")
                        driver.refresh()
                        time.sleep(10)

                        # Пытаемся ввести адрес заново
                        success, driver, wait = safe_send_keys(driver, wait, upload_address)

                        if not success:
                            # Записываем ошибку и продолжаем со СЛЕДУЮЩИМ адресом
                            all_results[upload_address] = {"error": "Не удалось ввести адрес после ошибки на сайте"}
                            continue  # Переходим к следующему адресу в цикле

                        # Если success=True, просто продолжаем выполнение

                except NoSuchElementException:
                    print("Кнопка поиска не найдена")
                    all_results[upload_address] = {"error": "Кнопка поиска не найдена"}
                    continue

                except Exception as e:
                    print(f"Ошибка при клике на кнопку поиска: {e}")
                    all_results[upload_address] = {"error": f"Ошибка поиска: {str(e)}"}
                    continue

                # Получаем количество кадастровых номеров по адресу
                try:
                    cad_numbers = wait.until(EC.visibility_of_all_elements_located(("xpath", "//div[@class='realestateobjects-wrapper__results__cadNumber']")))
                    numb_of_results = len(cad_numbers)
                    if numb_of_results == 0:
                        print(f"Не найдено результатов для адреса: {upload_address}")
                        all_results[upload_address] = {"error": "Не найдено результатов"}
                        continue
                except Exception as e:
                    print(f"Ошибка при поиске результатов для адреса {upload_address}: {e}")
                    all_results[upload_address] = {"error": f"Ошибка поиска: {str(e)}"}
                    continue

                address_data = []
                
                for numb in range(1, numb_of_results + 1):
                    data_dict = {}
                    try:
                        # Получение кадастрового номера и переход
                        cadastral_numb = wait.until(EC.visibility_of_element_located(("xpath", f"(//div[@class='realestateobjects-wrapper__results__cadNumber'])[{numb}]"))).text
                        wait.until(EC.visibility_of_element_located(("xpath", f"(//div[@class='realestateobjects-wrapper__results__cadNumber'])[{numb}]"))).click()
                        time.sleep(5)
                        
                        # Получение данных из модального окна
                        try:
                            name_elements = wait.until(EC.visibility_of_all_elements_located(("xpath", "//span[@class='build-card-wrapper__info__ul__subinfo__name']")))
                            info_elements = wait.until(EC.visibility_of_all_elements_located(("xpath", "//div[@class='build-card-wrapper__info__ul__subinfo__options__item__line']")))
                            
                            numb_answer = min(len(name_elements), len(info_elements))
                            for a in range(numb_answer):
                                name = name_elements[a].text
                                info = info_elements[a].text
                                data_dict[name] = info
                        except Exception as e:
                            print(f"Ошибка при получении данных из модального окна: {e}")
                        
                        # Добавляем кадастровый номер в данные
                        data_dict["Кадастровый номер"] = cadastral_numb
                        data_dict["Время запроса"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        # Закрытие справки
                        try:
                            close_btn = wait.until(EC.element_to_be_clickable(("xpath", "//button[@class='rros-ui-lib-modal__close-btn']")))
                            driver.execute_script("arguments[0].click();", close_btn)
                        except Exception as e:
                            print(f"Ошибка при закрытии модального окна: {e}")
                            # Пытаемся обновить страницу если не удалось закрыть
                            driver.get("https://lk.rosreestr.ru/eservices/real-estate-objects-online")

                        time.sleep(5)

                        address_data.append(data_dict)
                    
                    except Exception as e:
                        print(f"Ошибка при обработке кадастрового номера {numb} для адреса {upload_address}: {e}")
                        # Пытаемся закрыть модальное окно если открыто
                        try:
                            close_buttons = driver.find_elements("xpath", "//button[@class='rros-ui-lib-modal__close-btn']")
                            if close_buttons:
                                driver.execute_script("arguments[0].click();", close_buttons[0])
                        except:
                            pass
                        # Возвращаемся на страницу поиска
                        driver.get("https://lk.rosreestr.ru/eservices/real-estate-objects-online")
                        continue
                
                # Добавляем данные по адресу в общий словарь
                all_results[upload_address] = address_data

                # Сохраняем после каждых 10 новых адресов
                if new_addresses_count % 10 == 0:
                    print(f"Обработано {new_addresses_count} новых адресов. Сохраняем промежуточные результаты...")
                    try:
                        with open(note_file, 'w', encoding='utf-8') as f:
                            json.dump(all_results, f, ensure_ascii=False, indent=2)
                        print("Промежуточные результаты сохранены.")
                    except Exception as e:
                        print(f"Ошибка при сохранении результатов: {e}")

except Exception as e:
    print(f"Критическая ошибка в основном цикле: {e}")

finally:
    # Финальное сохранение всех результатов
    print(f"Завершение обработки. Всего просмотрено адресов: {address_count}, новых обработано: {new_addresses_count}")
    try:
        with open(note_file, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print("Финальные результаты сохранены.")
    except Exception as e:
        print(f"Ошибка при финальном сохранении: {e}")

    print("end code")
    try:
        driver.quit()
        sys.exit(1)
    except:
        pass
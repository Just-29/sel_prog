import os
import time


from datetime import datetime
from pathlib import Path
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver import Keys




# Пути
DRIVER_PATH = r"C:\Selenium\files\chromedriver-win64\chromedriver.exe"
CHROME_PATH = r"C:\Users\David\AppData\Local\Chromium\Application\chrome.exe"

# Закрываем все процессы Chrome перед запуском
os.system('taskkill /f /im chrome.exe 2>nul')
os.system('taskkill /f /im chromedriver.exe 2>nul')
time.sleep(2)

# Отключаем логи только webdriver-manager
os.environ['WDM_LOG_LEVEL'] = '0'

chrome_options = Options()
chrome_options.binary_location = CHROME_PATH



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
file_path = os.path.join(script_dir, "uploads", "Хадиков.pdf")
file_signature = os.path.join(script_dir, "uploads", "Хадиков.pdf.sig")
uploads_file_dir = script_dir / "uploads" / "uploads_files"

def wait_for_file_upload_by_title(driver, file_path, timeout=350):
    try:
        driver.find_element("xpath", "(//input[@type='file'])[3]").send_keys(str(file_path))
        
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located(("xpath", 
                f"//span[contains(@title, '{file_path.name}') and contains(@class, 'rros-ui-lib-file-upload__item__name')]"))
        )
        print(f"✅ Файл {file_path.name} успешно загружен")
        time.sleep(1)
        
        # JavaScript клик вместо обычного
        close_buttons = driver.find_elements("xpath", "//button[contains(@class, 'rros-ui-lib-modal__close-btn')]")
        if close_buttons:
            driver.execute_script("arguments[0].click();", close_buttons[0])
            print("✅ Модальное окно закрыто через JavaScript")
        else:
            print("⚠️ Кнопка закрытия не найдена")
        
        return False
        
    except Exception as e:
        print(f"❌ Файл {file_path.name} не загрузился: {e}")
        return True
    
def handle_apply_button(driver):
    """Обработка кнопки Применить с обработкой ошибок"""
    try:
        apply_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(("xpath", "//button[text()='Применить']"))
        )
        apply_button.click()
        print("✅ Кнопка 'Применить' нажата")
        return True
    except Exception as e:
        print(f"❌ Кнопка 'Применить' не найдена: {e}")
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

#driver.set_window_size(300, 300)

# Основной цикл обработки CSV файлов
for upload_file in uploads_file_dir.iterdir():
    if upload_file.is_file() and upload_file.suffix.lower() == '.csv':
        print(f"\n📁 Обработка файла: {upload_file.name}")
        
        driver.get("https://lk.rosreestr.ru/eservices/request-info-from-egrn/real-estate-object-or-its-rightholder")
        print("\n", "\t", "переход на страницу поиска по ЕГРН")
        time.sleep(10)
        #SCROLL_CATEGORY = ("xpath", "//input[@id='applicantCategory']")
        scroll_category = driver.find_element("xpath", "//input[@id='applicantCategory']")
        scroll_category.send_keys("Иные определенные федеральным законом")
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
        driver.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].regDate']").send_keys("23.12.2024")
        print("\n", "\t", "ввод даты")

        email = "eirc_trashbox@inbox.ru"
        driver.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].email']").clear()
        driver.find_element("xpath", "//input[@id='rorganizationOrGovernmentArray[0].email']").send_keys(email)
        driver.find_element("xpath", "//input[@id='fullNameDocumentAndAdditionalInformationArray[0].email']").clear()
        driver.find_element("xpath", "//input[@id='fullNameDocumentAndAdditionalInformationArray[0].email']").send_keys(email)
        driver.find_element("xpath", "//input[@id='requestAboutObject.deliveryActionEmail']").clear()
        driver.find_element("xpath", "//input[@id='requestAboutObject.deliveryActionEmail']").send_keys(email)
        print("ввод email")
        time.sleep(1)
        print("выбор типа документа")

        
        
        element = driver.find_element("xpath", "(//div[text()='Заполните адрес'])[1]")
        driver.execute_script("arguments[0].click();", element)

        print("\n", "\t", "открытие меню адреса")
        time.sleep(5)

        element = WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located(("xpath", "//input[@id='react-select-3-input']")))
        element.send_keys("Респ. Северная Осетия - Алания, г. Владикавказ, ул. Армянская, д.30 корп.1")
        time.sleep(3)
        element.send_keys(Keys.ARROW_DOWN)
        time.sleep(2)
        driver.find_element("xpath", "//input[@id='react-select-3-input']").send_keys(Keys.ENTER)
        print("нашел необходимый адресс")
        time.sleep(2)
        driver.find_element("xpath", "(//button[text()='Сохранить'])[1]").click()
        print("сохранен адресс") 
        time.sleep(2)

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
        driver.find_element("xpath", "//input[@id='userAuthorityConfirmationDocument.issuingAuthority']").send_keys("Правительство Республики Северная Осетия - Алания")
        time.sleep(1)
        print("\t ввел кем выдан")

        SCROL_VIPISKA = ("xpath", "//input[@id='react-select-6-input']")
        driver.find_element(*SCROL_VIPISKA).send_keys("Выписка из Единого государственного реестра недвижимости об объекте недвижимости")
        print("отправил")
        time.sleep(1)
        driver.find_element(*SCROL_VIPISKA).send_keys(Keys.ARROW_DOWN)
        print("СТРЕЛКА")
        time.sleep(1)
        driver.find_element(*SCROL_VIPISKA).send_keys(Keys.ENTER)
        print("энтер")
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

            # ПРОВЕРЯЕМ ошибку на каждой итерации
            error_element1 = driver.find_elements("xpath", "//div[text()='Объекты из CSV не добавлены в заявление']")
            error_element2 = driver.find_elements("xpath", "//*[contains(text(), 'Не удалось получить список объектов')]")

            if error_element1:
                print("❌ Обнаружена ошибка: Объекты из CSV не добавлены в заявление")
                # Если есть ошибка, продолжаем цикл
                loading_flag = True
                # Закрываем окно ошибки
                try:
                    close_buttons = driver.find_elements("xpath", "//button[contains(@class, 'close')] | //button[contains(text(), 'Закрыть')] | //button[@aria-label='Close']")
                    delete_button = driver.find_elements("xpath", "//span[@data-test-id='FileUpload.delete']")
                    if close_buttons:
                        close_buttons[0].click()
                        if delete_button:
                            delete_button[0].click()
                    else:
                        driver.find_element("xpath", "(//button[@class='rros-ui-lib-modal__close-btn'])[1]").click()
                except:
                    pass
            if error_element2:
                print("❌ Обнаружена ошибка: сайту не удалось получить список объектов из CSV")
                # Если есть ошибка, продолжаем цикл
                loading_flag = True
                # Закрываем окно ошибки
                try:
                    close_buttons = driver.find_elements("xpath", "//button[contains(@class, 'close')] | //button[contains(text(), 'Закрыть')] | //button[@aria-label='Close']")
                    delete_button = driver.find_elements("xpath", "//span[@data-test-id='FileUpload.delete']")
                    if close_buttons:
                        close_buttons[0].click()
                        if delete_button:
                            delete_button[0].click()
                    else:
                        driver.find_element("xpath", "(//button[@class='rros-ui-lib-modal__close-btn'])[1]").click()
                except:
                    pass

    if loading_flag and attempt < max_attempts:
        print("🔄 Повторная попытка через 5 секунд...")
        time.sleep(5)


        SCROL_VIPISKA = ("xpath", "//input[@id='react-select-6-input']")
        driver.find_element(*SCROL_VIPISKA).send_keys("Выписка из Единого государственного реестра недвижимости об объекте недвижимости")
        print("отправил")
        time.sleep(1)
        driver.find_element(*SCROL_VIPISKA).send_keys(Keys.ARROW_DOWN)
        print("СТРЕЛКА")
        time.sleep(1)
        driver.find_element(*SCROL_VIPISKA).send_keys(Keys.ENTER)
        print("энтер")
        time.sleep(1)
        driver.find_element("xpath", "//input[@id='requestAboutObject.deliveryActionEmail']").clear()
        driver.find_element("xpath", "//input[@id='requestAboutObject.deliveryActionEmail']").send_keys(email)
        print("email")
        time.sleep(1)

        # Пытаемся нажать кнопку Применить
        handle_apply_button(driver)
        
        time.sleep(1)
        input("enter")
        
        try:
            driver.find_element("xpath", "//button[text()='Далее']").click()
            time.sleep(1)
            driver.find_element("xpath", "//button[text()='Далее']").click()
            print("✅ Оба шага 'Далее' выполнены")
        except Exception as e:
            print(f"❌ Ошибка при нажатии 'Далее': {e}")
        
        time.sleep(180)
    
    try:
        wait.until(EC.presence_of_element_located(("xpath", "//div[text()='Добавлено объектов из CSV-файла:']")))
        print("✅ CSV-файл найден, продолжаем работу")
    
    except:
        print("❌ CSV-файл не появился в течение 120 секунд")
    

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
    save_selenium_note(driver, upload_file)
    time.sleep(10)

print("end code")
driver.quit()


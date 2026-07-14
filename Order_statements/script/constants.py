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
SESSION_EXPIRED_MARKERS = ("Время сессии истекло", "сессии истекло", "время сессии истекло")
FORM_PAGE_URL = (
    "https://lk.rosreestr.ru/eservices/request-info-from-egrn/real-estate-object-or-its-rightholder"
)
FORM_PAGE_READY_MAX_ATTEMPTS = 5
LOGIN_URL_MARKERS = ("gosuslugi", "esia", "esia.gosuslugi")
CSV_APPLY_BUTTON_XPATH = "//button[contains(@class, 'my-objects-modal__selected-btn')]"

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
LOGIN_ROLE_LIST_XPATH = (
    "//div[contains(@class, 'role-selector__list')]",
    "//div[contains(@class, 'roles-selector')]",
)
LOGIN_ROLE_XPATHS = (
    f"//button[contains(@class, 'role-selector-list__item')]"
    f"[.//span[contains(@class, 'role-selector-list__item-name') and contains(., '{LOGIN_MINISTRY}')]]",
    f"//button[contains(@class, 'role-selector-list__item')]"
    f"//span[contains(@class, 'role-selector-list__item-name') and contains(., '{LOGIN_MINISTRY}')]",
    f"//div[contains(@class, 'role-selector-list__item-content')]"
    f"[.//span[contains(@class, 'role-selector-list__item-name') and contains(., '{LOGIN_MINISTRY}')]]",
    f"//span[contains(@class, 'role-selector-list__item-name') and contains(., '{LOGIN_MINISTRY}')]",
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
VIPISKA_TEXT_2 = (
    "Выписка из Единого государственного реестра недвижимости об объекте недвижимости"
)
VIPISKA_MARKER = "Выписка из Единого государственного реестра"

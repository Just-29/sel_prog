"""Пути проекта и переменные окружения."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT.parent / "files" / ".env")

UPLOADS_CSV_DIR = PROJECT_ROOT / "uploads_CSV"
FUTURE_UPLOADS_DIR = PROJECT_ROOT / "future_uploads"
UPLOADS_DIR = PROJECT_ROOT / "uploads"
LOG_DIR = PROJECT_ROOT / "logs"
SCREENSHOTS_DIR = LOG_DIR / "screenshots"
DIAGNOSTICS_DIR = LOG_DIR / "diagnostics"
RESULTS_LOG = PROJECT_ROOT / "results.log"
SCHEDULE_INI = PROJECT_ROOT / "schedule.ini"

for _d in (UPLOADS_CSV_DIR, FUTURE_UPLOADS_DIR, UPLOADS_DIR, LOG_DIR, SCREENSHOTS_DIR, DIAGNOSTICS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DRIVER_PATH = os.getenv("DRIVER_PATH")
CHROME_PATH = os.getenv("CHROME_PATH")
CHROME_PROFILE_PATH = os.getenv("CHROME_PROFILE_PATH")
EMAIL = os.getenv("EMAIL")
DOCUMENT_NUMBER = os.getenv("DOCUMENT_NUMBER")
DOCUMENT_DATE = os.getenv("DOCUMENT_DATE")
ISSUING_AUTHORITY = os.getenv("ISSUING_AUTHORITY")
MIN_ADDRESS = os.getenv("MIN_ADDRESS")
PDF_FILE_NAME = os.getenv("PDF_FILE_NAME")
SIGNATURE_FILE_NAME = os.getenv("SIGNATURE_FILE_NAME")
QWART_EMAIL = os.getenv("QWART_EMAIL")
CORRECTION = os.getenv("CORRECTION")

WEBDRIVER_WAIT_TIMEOUT = 1500

"""Очередь CSV: подготовка файлов из future_uploads в uploads_CSV."""
from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

from .config import FUTURE_UPLOADS_DIR, RESULTS_LOG, SCHEDULE_INI, UPLOADS_CSV_DIR
from .logging_utils import log_info, log_warning

_SUCCESS_LINE_RE = re.compile(r"УСПЕХ:\s*Файл\s+(.+?)\s+отправлен", re.IGNORECASE)
_TODAY_SUCCESS_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}\]\s+УСПЕХ:",
    re.IGNORECASE,
)


def _natural_sort_key(path: Path) -> list:
    parts = re.split(r"(\d+)", path.name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def _read_schedule_ini() -> dict[str, str]:
    if not SCHEDULE_INI.is_file():
        return {}
    config: dict[str, str] = {}
    for line in SCHEDULE_INI.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        config[key.strip().lower()] = value.strip()
    return config


def _parse_positive_int(raw: str | None, default: int = 0) -> int:
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return max(0, value)


def get_files_per_run() -> int:
    """0 — без лимита на один запуск."""
    return _parse_positive_int(_read_schedule_ini().get("files_per_run"), default=0)


def get_daily_limit() -> int:
    """0 — без суточного лимита."""
    return _parse_positive_int(_read_schedule_ini().get("daily_limit"), default=0)


def get_sent_filenames() -> set[str]:
    """Имена CSV, успешно отправленные ранее (по results.log)."""
    if not RESULTS_LOG.is_file():
        return set()
    sent: set[str] = set()
    for line in RESULTS_LOG.read_text(encoding="utf-8").splitlines():
        match = _SUCCESS_LINE_RE.search(line)
        if match:
            sent.add(Path(match.group(1).strip()).name)
    return sent


def count_sent_today() -> int:
    if not RESULTS_LOG.is_file():
        return 0
    today = date.today().isoformat()
    count = 0
    for line in RESULTS_LOG.read_text(encoding="utf-8").splitlines():
        date_match = _TODAY_SUCCESS_RE.match(line)
        if date_match and date_match.group(1) == today:
            count += 1
    return count


def list_csv_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]
    return sorted(files, key=_natural_sort_key)


def uploads_csv_has_files() -> bool:
    return bool(list_csv_files(UPLOADS_CSV_DIR))


def list_pending_future_uploads() -> list[Path]:
    sent = get_sent_filenames()
    pending = [p for p in list_csv_files(FUTURE_UPLOADS_DIR) if p.name not in sent]
    return pending


def _staging_limit() -> int | None:
    """Сколько файлов можно подготовить в этом запуске. None — без ограничения."""
    limits: list[int] = []
    per_run = get_files_per_run()
    if per_run > 0:
        limits.append(per_run)

    daily_limit = get_daily_limit()
    if daily_limit > 0:
        remaining_today = daily_limit - count_sent_today()
        if remaining_today <= 0:
            return 0
        limits.append(remaining_today)

    if not limits:
        return None
    return min(limits)


def stage_files_from_future_uploads() -> list[Path]:
    """
    Копирует CSV из future_uploads в uploads_CSV, если uploads_CSV пуста.
    После успешного копирования исходник удаляется из future_uploads.
    Возвращает список скопированных файлов.
    """
    FUTURE_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    if uploads_csv_has_files():
        existing = [p.name for p in list_csv_files(UPLOADS_CSV_DIR)]
        log_info(
            "Подготовка очереди пропущена: в uploads_CSV уже есть файлы",
            stage="upload_queue",
            files=", ".join(existing),
        )
        return []

    pending = list_pending_future_uploads()
    if not pending:
        log_info(
            "Нет новых CSV в future_uploads для подготовки",
            stage="upload_queue",
        )
        return []

    limit = _staging_limit()
    if limit == 0:
        log_info(
            "Подготовка очереди пропущена: достигнут суточный лимит отправок",
            stage="upload_queue",
            daily_limit=get_daily_limit(),
            sent_today=count_sent_today(),
        )
        return []

    to_stage = pending if limit is None else pending[:limit]
    staged: list[Path] = []

    for source in to_stage:
        destination = UPLOADS_CSV_DIR / source.name
        if destination.exists():
            log_warning(
                "Файл уже есть в uploads_CSV, пропуск копирования",
                stage="upload_queue",
                file=source.name,
            )
            continue
        shutil.copy2(source, destination)
        staged.append(destination)
        try:
            source.unlink()
            log_info(
                f"Скопирован из future_uploads и удалён источник: {source.name}",
                stage="upload_queue",
                file=source.name,
            )
        except Exception as e:
            log_warning(
                f"Скопирован в uploads_CSV, но не удалось удалить из future_uploads: {source.name}",
                stage="upload_queue",
                file=source.name,
                exc=e,
            )

    if staged:
        log_info(
            f"Подготовлено файлов к отправке: {len(staged)}",
            stage="upload_queue",
            files=", ".join(p.name for p in staged),
        )
    return staged

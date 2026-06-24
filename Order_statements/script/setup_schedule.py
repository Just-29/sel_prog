"""Настройка автозапуска через Планировщик заданий Windows (пробуждение из сна)."""
from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INI_PATH = PROJECT_ROOT / "schedule.ini"
RUN_BAT = PROJECT_ROOT / "run_scheduled.bat"
TASK_NAME = "OrderStatements_Rosreestr"
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", NS)

DAY_MAP = {
    "пн": "Monday",
    "вт": "Tuesday",
    "ср": "Wednesday",
    "чт": "Thursday",
    "пт": "Friday",
    "сб": "Saturday",
    "вс": "Sunday",
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


def read_ini(path: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    if not path.is_file():
        raise FileNotFoundError(f"Не найден файл настроек: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        config[key.strip().lower()] = value.strip()
    return config


def parse_enabled(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


def parse_time(raw: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw.strip())
    if not match:
        raise ValueError(f"Неверный формат time: {raw!r} (ожидается ЧЧ:ММ)")
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Недопустимое время: {raw}")
    return hour, minute


def parse_days(raw: str) -> list[str] | None:
    normalized = raw.strip().lower()
    if normalized == "daily":
        return None
    if normalized == "weekdays":
        return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    parts = re.split(r"[,;\s]+", normalized)
    days: list[str] = []
    for part in parts:
        if not part:
            continue
        mapped = DAY_MAP.get(part)
        if mapped is None:
            raise ValueError(
                f"Неизвестный день: {part!r}. Используйте daily, weekdays или пн,вт,..."
            )
        if mapped not in days:
            days.append(mapped)
    if not days:
        raise ValueError("Укажите days=daily, days=weekdays или список дней")
    return days


def delete_task() -> None:
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def enable_wake_timers() -> None:
    commands = [
        ["powercfg", "/SETACVALUEINDEX", "SCHEME_CURRENT", "SUB_SLEEP", "RTCWAKE", "1"],
        ["powercfg", "/SETDCVALUEINDEX", "SCHEME_CURRENT", "SUB_SLEEP", "RTCWAKE", "1"],
        ["powercfg", "/SETACTIVE", "SCHEME_CURRENT"],
    ]
    for cmd in commands:
        subprocess.run(cmd, capture_output=True)


def build_task_xml(hour: int, minute: int, days: list[str] | None) -> str:
    start = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    start_boundary = start.strftime("%Y-%m-%dT%H:%M:%S")

    task = ET.Element(f"{{{NS}}}Task", version="1.4")
    registration = ET.SubElement(task, f"{{{NS}}}RegistrationInfo")
    ET.SubElement(registration, f"{{{NS}}}Description").text = (
        "Автозапуск Order_statements. Настройки: schedule.ini"
    )
    ET.SubElement(registration, f"{{{NS}}}Author").text = "Order_statements"

    triggers = ET.SubElement(task, f"{{{NS}}}Triggers")
    calendar = ET.SubElement(triggers, f"{{{NS}}}CalendarTrigger")
    ET.SubElement(calendar, f"{{{NS}}}StartBoundary").text = start_boundary
    ET.SubElement(calendar, f"{{{NS}}}Enabled").text = "true"

    if days is None:
        schedule = ET.SubElement(calendar, f"{{{NS}}}ScheduleByDay")
        ET.SubElement(schedule, f"{{{NS}}}DaysInterval").text = "1"
    else:
        schedule = ET.SubElement(calendar, f"{{{NS}}}ScheduleByWeek")
        week_days = ET.SubElement(schedule, f"{{{NS}}}DaysOfWeek")
        for day in days:
            ET.SubElement(week_days, f"{{{NS}}}{day}")

    settings = ET.SubElement(task, f"{{{NS}}}Settings")
    ET.SubElement(settings, f"{{{NS}}}MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(settings, f"{{{NS}}}DisallowStartIfOnBatteries").text = "false"
    ET.SubElement(settings, f"{{{NS}}}StopIfGoingOnBatteries").text = "false"
    ET.SubElement(settings, f"{{{NS}}}AllowHardTerminate").text = "true"
    ET.SubElement(settings, f"{{{NS}}}StartWhenAvailable").text = "true"
    ET.SubElement(settings, f"{{{NS}}}RunOnlyIfNetworkAvailable").text = "false"
    ET.SubElement(settings, f"{{{NS}}}WakeToRun").text = "true"
    ET.SubElement(settings, f"{{{NS}}}ExecutionTimeLimit").text = "PT12H"
    ET.SubElement(settings, f"{{{NS}}}Enabled").text = "true"
    ET.SubElement(settings, f"{{{NS}}}Hidden").text = "false"

    actions = ET.SubElement(task, f"{{{NS}}}Actions")
    action = ET.SubElement(actions, f"{{{NS}}}Exec")
    ET.SubElement(action, f"{{{NS}}}Command").text = str(RUN_BAT)
    ET.SubElement(action, f"{{{NS}}}WorkingDirectory").text = str(PROJECT_ROOT)

    return '<?xml version="1.0" encoding="UTF-16"?>\n' + ET.tostring(task, encoding="unicode")


def create_task(hour: int, minute: int, days: list[str] | None) -> None:
    xml_path = PROJECT_ROOT / "logs" / "_schedule_task.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(build_task_xml(hour, minute, days), encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"schtasks не создал задание: {detail}")


def format_days_label(days: list[str] | None) -> str:
    if days is None:
        return "каждый день"
    ru = {v: k for k, v in DAY_MAP.items() if len(k) == 2}
    return ", ".join(ru.get(day, day) for day in days)


def main() -> int:
    quiet = "--quiet" in sys.argv

    def info(message: str) -> None:
        if not quiet:
            print(message)

    try:
        config = read_ini(INI_PATH)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    if not parse_enabled(config.get("enabled")):
        delete_task()
        info("Автозапуск отключён (enabled=false в schedule.ini).")
        return 0

    if not RUN_BAT.is_file():
        print(f"Не найден скрипт запуска: {RUN_BAT}", file=sys.stderr)
        return 1

    try:
        hour, minute = parse_time(config.get("time", "08:00"))
        days = parse_days(config.get("days", "weekdays"))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    try:
        create_task(hour, minute, days)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

    enable_wake_timers()

    info("")
    info("Автозапуск настроен:")
    info(f"  Задание: {TASK_NAME}")
    info(f"  Время:   {hour:02d}:{minute:02d}")
    info(f"  Дни:     {format_days_label(days)}")
    info(f"  Скрипт:  {RUN_BAT}")
    info("")
    info("Чтобы изменить — отредактируйте schedule.ini и снова запустите setup_schedule.bat")
    info("ПК должен быть в сне/гибернации (не выключен), пользователь — в системе.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Автозакрытие нативных окон Windows (Госплагин, КриптоПро, предупреждения ОС).

КриптоПро «Подтверждение доступа» — классический Win32-диалог (#32770).
Два таких окна часто поочерёдно перехватывают фокус; SendMessage(BM_CLICK)
на кнопку «Да» работает без активации окна.
"""
from __future__ import annotations

import os
import sys
import threading
import time

from .logging_utils import log_info, log_warning

_STOP = threading.Event()
_THREAD: threading.Thread | None = None

CRYPTOPRO_ACCESS_TITLE_PATTERNS = (
    "подтверждение доступа",
    "подтверждение действия",
)

CRYPTOPRO_DIALOG_CLASS = "#32770"
CRYPTOPRO_YES_LABELS = frozenset({"да", "yes"})
_WIN32_YES_CONTROL_IDS = (6, 1)  # IDYES, IDOK

DEFAULT_WINDOW_PATTERNS = (
    "госплагин",
    "gosplugin",
    "криптопро",
    "cryptopro",
)

DEFAULT_BUTTON_LABELS = (
    "Да",
    "&Да",
    "Yes",
    "&Yes",
    "OK",
    "ОК",
    "Ok",
)


def _enabled() -> bool:
    return os.getenv("AUTO_DISMISS_NATIVE_DIALOGS", "true").lower() not in (
        "0",
        "false",
        "no",
    )


def _patterns() -> tuple[str, ...]:
    raw = os.getenv("NATIVE_DIALOG_WINDOW_PATTERNS", "").strip()
    if raw:
        return tuple(p.strip().lower() for p in raw.split("|") if p.strip())
    return DEFAULT_WINDOW_PATTERNS


def _button_labels() -> tuple[str, ...]:
    raw = os.getenv("NATIVE_DIALOG_BUTTON_LABELS", "").strip()
    if raw:
        return tuple(b.strip() for b in raw.split("|") if b.strip())
    return DEFAULT_BUTTON_LABELS


def _win32_available() -> bool:
    try:
        import win32gui  # noqa: F401
        return True
    except ImportError:
        return False


def _normalize_label(text: str) -> str:
    return (text or "").replace("&", "").strip().lower()


def _dialog_title_matches(title: str) -> bool:
    title_lower = (title or "").strip().lower()
    return any(p in title_lower for p in CRYPTOPRO_ACCESS_TITLE_PATTERNS)


def _find_cryptopro_access_hwnds() -> list[int]:
    """Все видимые окна «Подтверждение доступа» (#32770) — обычно 1–2 штуки."""
    import win32gui

    hwnds: list[int] = []

    def callback(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            if win32gui.GetClassName(hwnd) != CRYPTOPRO_DIALOG_CLASS:
                return True
            title = win32gui.GetWindowText(hwnd)
            if not _dialog_title_matches(title):
                return True
            hwnds.append(hwnd)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(callback, None)
    return hwnds


def _find_yes_button_hwnd(dialog_hwnd: int) -> int | None:
    import win32gui

    for control_id in _WIN32_YES_CONTROL_IDS:
        try:
            btn = win32gui.GetDlgItem(dialog_hwnd, control_id)
            if btn and win32gui.IsWindowVisible(btn):
                return btn
        except Exception:
            continue

    found: list[int] = []

    def child_cb(child, _):
        try:
            if win32gui.GetClassName(child) != "Button":
                return True
            if _normalize_label(win32gui.GetWindowText(child)) in CRYPTOPRO_YES_LABELS:
                found.append(child)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(dialog_hwnd, child_cb, None)
    except Exception:
        pass
    return found[0] if found else None


def _bm_click(hwnd: int) -> bool:
    import win32api
    import win32con
    try:
        win32api.SendMessage(hwnd, win32con.BM_CLICK, 0, 0)
        return True
    except Exception:
        return False


def _click_yes_on_dialog_hwnd(dialog_hwnd: int) -> bool:
    btn = _find_yes_button_hwnd(dialog_hwnd)
    if not btn:
        return False
    return _bm_click(btn)


def _handle_cryptopro_access_dialogs() -> int:
    """
    Нажимает «Да» во ВСЕХ окнах «Подтверждение доступа» за один проход.
    SendMessage не требует фокуса — решает проблему двух окон, переключающихся между собой.
    """
    if not _win32_available():
        return 0

    clicked = 0
    for dialog_hwnd in _find_cryptopro_access_hwnds():
        import win32gui

        title = win32gui.GetWindowText(dialog_hwnd) or "(без заголовка)"
        if _click_yes_on_dialog_hwnd(dialog_hwnd):
            log_info(
                f"КриптоПро: BM_CLICK «Да» в «{title}» (hwnd={dialog_hwnd})",
                stage="native_dialog",
                dialog="cryptopro_access",
                method="win32_sendmessage",
            )
            clicked += 1
    return clicked


def _cryptopro_dialogs_remain() -> int:
    return len(_find_cryptopro_access_hwnds())


def _try_click_button_pywinauto(win, label: str) -> bool:
    attempts = (
        {"title": label, "class_name": "Button"},
        {"title_re": f".*{_normalize_label(label)}.*", "class_name": "Button"},
    )
    for kwargs in attempts:
        try:
            btn = win.child_window(**kwargs)
            if btn.exists(timeout=0):
                try:
                    btn.click()
                except Exception:
                    btn.click_input()
                return True
        except Exception:
            continue
    return False


def _scan_other_dialogs(patterns: tuple[str, ...], button_labels: tuple[str, ...]) -> int:
    """Прочие окна плагинов (Госплагин OK) — только win32, только по заголовку."""
    try:
        from pywinauto import Desktop
    except ImportError:
        return 0

    clicked = 0
    try:
        windows = Desktop(backend="win32").windows()
    except Exception:
        return 0

    for win in windows:
        try:
            if not win.is_visible():
                continue
            title = (win.window_text() or "").strip()
            if not title or _dialog_title_matches(title):
                continue
            title_lower = title.lower()
            if not any(p in title_lower for p in patterns):
                continue
            for label in button_labels:
                if _try_click_button_pywinauto(win, label):
                    log_info(
                        f"Нажата «{label}» в «{title}»",
                        stage="native_dialog",
                        backend="win32",
                    )
                    clicked += 1
                    break
        except Exception:
            continue
    return clicked


def _scan_and_click(patterns: tuple[str, ...], button_labels: tuple[str, ...]) -> int:
    return _handle_cryptopro_access_dialogs() + _scan_other_dialogs(patterns, button_labels)


def _watch_loop(
    duration: float,
    poll_interval: float,
    patterns: tuple[str, ...],
    button_labels: tuple[str, ...],
) -> None:
    deadline = time.time() + duration
    while time.time() < deadline and not _STOP.is_set():
        _scan_and_click(patterns, button_labels)
        time.sleep(poll_interval)


def start_native_dialog_watcher(
    duration: float | None = None,
    poll_interval: float | None = None,
) -> bool:
    global _THREAD

    if sys.platform != "win32":
        return False
    if not _enabled():
        log_info(
            "Автозакрытие нативных окон отключено (AUTO_DISMISS_NATIVE_DIALOGS=false)",
            stage="native_dialog",
        )
        return False

    if not _win32_available():
        log_warning(
            "win32gui недоступен — установите pywin32 (pip install pywinauto)",
            stage="native_dialog",
        )
        return False

    if duration is None:
        duration = float(os.getenv("NATIVE_DIALOG_WATCH_SEC", "180"))
    if poll_interval is None:
        poll_interval = float(os.getenv("NATIVE_DIALOG_POLL_SEC", "0.2"))

    patterns = _patterns()
    button_labels = _button_labels()

    _STOP.clear()
    if _THREAD and _THREAD.is_alive():
        return True

    def run() -> None:
        log_info(
            f"Слежение за окнами КриптоПро ({duration:.0f} сек, шаг {poll_interval} сек)",
            stage="native_dialog",
            method="win32_sendmessage",
        )
        _watch_loop(duration, poll_interval, patterns, button_labels)
        if not _STOP.is_set():
            log_info("Слежение за нативными окнами завершено по таймауту", stage="native_dialog")

    _THREAD = threading.Thread(target=run, daemon=True, name="native-dialog-watcher")
    _THREAD.start()
    return True


def stop_native_dialog_watcher() -> None:
    _STOP.set()


def pulse_cryptopro_access(seconds: float | None = None) -> int:
    """
    Закрывает 1–2 окна «Подтверждение доступа».
    Пока хотя бы одно окно видно — продолжает нажимать «Да» во всех найденных.
    """
    if sys.platform != "win32" or not _enabled() or not _win32_available():
        return 0

    if seconds is None:
        seconds = float(os.getenv("CRYPTOPRO_ACCESS_PULSE_SEC", "35"))

    total = 0
    deadline = time.time() + seconds
    poll = float(os.getenv("CRYPTOPRO_ACCESS_POLL_SEC", "0.15"))

    while time.time() < deadline:
        remaining = _cryptopro_dialogs_remain()
        if remaining == 0:
            if total > 0:
                log_info(
                    f"КриптоПро: все окна «Подтверждение доступа» закрыты ({total} кликов)",
                    stage="native_dialog",
                )
                break
            time.sleep(poll)
            continue

        if remaining > 1:
            log_info(
                f"КриптоПро: обнаружено окон «Подтверждение доступа»: {remaining}",
                stage="native_dialog",
            )

        n = _handle_cryptopro_access_dialogs()
        total += n
        time.sleep(poll)

    if _cryptopro_dialogs_remain() > 0:
        log_warning(
            f"КриптоПро: остались незакрытые окна ({_cryptopro_dialogs_remain()} шт.)",
            stage="native_dialog",
        )

    return total


def pulse_native_dialogs(seconds: float | None = None) -> int:
    if sys.platform != "win32" or not _enabled():
        return 0

    if seconds is None:
        seconds = float(os.getenv("NATIVE_DIALOG_PULSE_SEC", "12"))

    total = pulse_cryptopro_access(seconds)
    deadline = time.time() + max(0.0, seconds * 0.3)
    patterns = _patterns()
    button_labels = _button_labels()
    while time.time() < deadline:
        total += _scan_other_dialogs(patterns, button_labels)
        time.sleep(0.2)
    return total

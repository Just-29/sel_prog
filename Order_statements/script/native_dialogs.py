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

# Госплагин: Qt-окно gosuslugi_plugin.exe, заголовок «Подтверждение», кнопки OK/Отмена.
GOSPLUGIN_WINDOW_CLASS = "Qt5156QWindowIcon"
GOSPLUGIN_TITLE_PATTERNS = (
    "подтверждение",
    "госплагин",
    "gosplugin",
)

CRYPTOPRO_DIALOG_CLASS = "#32770"
CRYPTOPRO_YES_LABELS = frozenset({"да", "yes", "ok", "ок"})
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

GOSPLUGIN_OK_LABELS = ("OK", "ОК", "Ok")


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


def _gosplugin_title_matches(title: str) -> bool:
    title_lower = (title or "").strip().lower()
    return any(p in title_lower for p in GOSPLUGIN_TITLE_PATTERNS)


def _find_gosplugin_qt_hwnds() -> list[int]:
    """Поиск окон Госплагин через win32 (работает с любого монитора и потока)."""
    if not _win32_available():
        return []

    import win32gui

    hwnds: list[int] = []

    def callback(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            cls = win32gui.GetClassName(hwnd)
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if cls == GOSPLUGIN_WINDOW_CLASS:
                hwnds.append(hwnd)
            elif cls.startswith("Qt") and title and _gosplugin_title_matches(title):
                hwnds.append(hwnd)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(callback, None)
    return hwnds


def _find_gosplugin_qt_windows_uia():
    if not _find_gosplugin_qt_hwnds():
        return []

    try:
        from pywinauto import Desktop
    except ImportError:
        return []

    targets = {hwnd for hwnd in _find_gosplugin_qt_hwnds()}
    matches = []
    try:
        windows = Desktop(backend="uia").windows()
    except Exception:
        return []

    for win in windows:
        try:
            if not win.is_visible():
                continue
            if int(win.handle) in targets:
                matches.append(win)
        except Exception:
            continue
    return matches


def _focus_window(hwnd: int) -> None:
    import win32con
    import win32gui

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        try:
            win32gui.BringWindowToTop(hwnd)
        except Exception:
            pass


def _click_at_center(rect) -> bool:
    try:
        import win32api
        import win32con

        x = int((rect.left + rect.right) / 2)
        y = int((rect.top + rect.bottom) / 2)
        win32api.SetCursorPos((x, y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)
        return True
    except Exception:
        return False


def _click_uia_button(btn) -> bool:
    try:
        btn.invoke()
        return True
    except Exception:
        try:
            btn.click_input()
            return True
        except Exception:
            try:
                return _click_at_center(btn.rectangle())
            except Exception:
                return False


def _handle_gosplugin_hwnd(hwnd: int) -> bool:
    import win32gui

    if threading.current_thread() is not threading.main_thread():
        return False

    try:
        from pywinauto import Application
    except ImportError:
        return False

    title = (win32gui.GetWindowText(hwnd) or "").strip() or "(без заголовка)"

    _focus_window(hwnd)
    time.sleep(0.15)

    try:
        app = Application(backend="uia").connect(handle=hwnd, timeout=3)
        dlg = app.window(handle=hwnd)

        labels = (*GOSPLUGIN_OK_LABELS, *_button_labels())
        for label in dict.fromkeys(labels):
            try:
                ok = dlg.child_window(title=label, control_type="Button")
                if not ok.exists(timeout=0):
                    continue
                try:
                    if not ok.is_enabled():
                        continue
                except Exception:
                    pass
                if _click_uia_button(ok):
                    log_info(
                        f"Госплагин: нажата «{label}» в «{title}» (hwnd={hwnd})",
                        stage="native_dialog",
                        backend="uia",
                        dialog="gosplugin_qt",
                        method="invoke",
                    )
                    return True
            except Exception:
                continue
    except Exception as exc:
        log_warning(
            f"Госплагин: не удалось нажать OK в «{title}» (hwnd={hwnd})",
            stage="native_dialog",
            exc=exc,
        )
    return False


def _handle_gosplugin_qt_dialogs() -> int:
    """
    Окна Госплагин (gosuslugi_plugin.exe): Qt5156QWindowIcon, кнопка OK.
    UIA работает только из главного потока; hwnd ищем через win32.
    """
    hwnds = _find_gosplugin_qt_hwnds()
    if not hwnds:
        return 0

    if threading.current_thread() is not threading.main_thread():
        log_info(
            f"Госплагин: обнаружено окон {len(hwnds)} (ожидает главный поток)",
            stage="native_dialog",
            hwnds=",".join(str(h) for h in hwnds),
        )
        return 0

    clicked = 0
    for hwnd in hwnds:
        if _handle_gosplugin_hwnd(hwnd):
            clicked += 1
    return clicked


def dismiss_pending_native_dialogs() -> int:
    """Быстрое закрытие всех известных нативных окон (для цикла ожидания в login)."""
    if sys.platform != "win32" or not _enabled():
        return 0
    return (
        _handle_gosplugin_qt_dialogs()
        + _handle_cryptopro_access_dialogs()
        + _handle_access_confirmation_pywinauto()
    )


def _gosplugin_qt_dialogs_remain() -> int:
    return len(_find_gosplugin_qt_hwnds())


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
    Нажимает «Да» во ВСЕХ окнах «Подтверждение доступа» (#32770) за один проход.
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


def _handle_access_confirmation_pywinauto() -> int:
    """
    Fallback для «Подтверждение доступа» не класса #32770 (часто Госплагин).
    Такие окна раньше пропускались: win32 ловит только #32770, а _scan_other_dialogs
    игнорировал этот заголовок.
    """
    try:
        from pywinauto import Desktop
    except ImportError:
        return 0

    clicked = 0
    handled_hwnds: set[int] = set()
    cryptopro_hwnds = set(_find_cryptopro_access_hwnds())

    for backend in ("uia", "win32"):
        try:
            windows = Desktop(backend=backend).windows()
        except Exception:
            continue

        for win in windows:
            try:
                if not win.is_visible():
                    continue
                hwnd = int(win.handle)
                if hwnd in handled_hwnds or hwnd in cryptopro_hwnds:
                    continue
                title = (win.window_text() or "").strip()
                if not title or not _dialog_title_matches(title):
                    continue
                if backend == "win32" and _win32_available():
                    import win32gui

                    if win32gui.GetClassName(hwnd) == CRYPTOPRO_DIALOG_CLASS:
                        continue
                for label in _button_labels():
                    if _try_click_button_pywinauto(win, label):
                        log_info(
                            f"Нажата «{label}» в «{title}»",
                            stage="native_dialog",
                            backend=backend,
                            dialog="access_confirmation",
                        )
                        handled_hwnds.add(hwnd)
                        clicked += 1
                        break
            except Exception:
                continue
    return clicked


def _access_confirmation_dialogs_remain() -> int:
    count = _gosplugin_qt_dialogs_remain()
    if count:
        return count

    count = len(_find_cryptopro_access_hwnds())
    if count:
        return count

    try:
        from pywinauto import Desktop
    except ImportError:
        return 0

    for backend in ("uia", "win32"):
        try:
            for win in Desktop(backend=backend).windows():
                if not win.is_visible():
                    continue
                title = (win.window_text() or "").strip()
                if title and _dialog_title_matches(title):
                    return 1
        except Exception:
            continue
    return 0


def _cryptopro_dialogs_remain() -> int:
    return _access_confirmation_dialogs_remain()


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
    """Прочие окна плагинов (Госплагин и т.п.) — только win32, только по заголовку."""
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
            if not title:
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
    # Госплагин (UIA) — только из главного потока; фоновый watcher закрывает КриптоПро.
    return (
        _handle_cryptopro_access_dialogs()
        + _handle_access_confirmation_pywinauto()
        + _scan_other_dialogs(patterns, button_labels)
    )


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
    *,
    restart: bool = False,
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
        duration = float(os.getenv("NATIVE_DIALOG_WATCH_SEC", "300"))
    if poll_interval is None:
        poll_interval = float(os.getenv("NATIVE_DIALOG_POLL_SEC", "0.2"))

    patterns = _patterns()
    button_labels = _button_labels()

    if restart and _THREAD and _THREAD.is_alive():
        _STOP.set()
        _THREAD.join(timeout=2.0)

    _STOP.clear()
    if _THREAD and _THREAD.is_alive():
        return True

    def run() -> None:
        log_info(
            f"Слежение за нативными окнами ({duration:.0f} сек, шаг {poll_interval} сек)",
            stage="native_dialog",
            method="win32_sendmessage+uia",
        )
        _watch_loop(duration, poll_interval, patterns, button_labels)
        if not _STOP.is_set():
            log_info("Слежение за нативными окнами завершено по таймауту", stage="native_dialog")

    _THREAD = threading.Thread(target=run, daemon=True, name="native-dialog-watcher")
    _THREAD.start()
    return True


def restart_native_dialog_watcher(
    duration: float | None = None,
    poll_interval: float | None = None,
) -> bool:
    """Перезапускает фоновое слежение (нужно перед выбором сертификата/роли)."""
    return start_native_dialog_watcher(duration, poll_interval, restart=True)


def stop_native_dialog_watcher() -> None:
    _STOP.set()


def pulse_cryptopro_access(seconds: float | None = None) -> int:
    """
    Закрывает 1–2 окна «Подтверждение доступа».
    Пока хотя бы одно окно видно — продолжает нажимать «Да» во всех найденных.
    """
    if sys.platform != "win32" or not _enabled():
        return 0

    if seconds is None:
        seconds = float(os.getenv("CRYPTOPRO_ACCESS_PULSE_SEC", "35"))

    total = 0
    deadline = time.time() + seconds
    poll = float(os.getenv("CRYPTOPRO_ACCESS_POLL_SEC", "0.15"))
    appear_grace = float(os.getenv("NATIVE_DIALOG_APPEAR_GRACE_SEC", "5"))
    empty_since = time.time()

    while time.time() < deadline:
        remaining = _access_confirmation_dialogs_remain()
        if remaining == 0:
            if total > 0:
                log_info(
                    f"Все окна «Подтверждение доступа» закрыты ({total} кликов)",
                    stage="native_dialog",
                )
                break
            if time.time() - empty_since >= appear_grace:
                break
            time.sleep(poll)
            continue
        empty_since = time.time()

        if remaining > 1:
            log_info(
                f"Обнаружено окон «Подтверждение доступа»: {remaining}",
                stage="native_dialog",
            )

        n = (
            _handle_gosplugin_qt_dialogs()
            + _handle_cryptopro_access_dialogs()
            + _handle_access_confirmation_pywinauto()
        )
        total += n
        time.sleep(poll)

    remaining = _access_confirmation_dialogs_remain()
    if remaining > 0:
        log_warning(
            f"Остались незакрытые окна подтверждения ({remaining} шт.)",
            stage="native_dialog",
        )

    return total


def pulse_native_dialogs(seconds: float | None = None) -> int:
    if sys.platform != "win32" or not _enabled():
        return 0

    if seconds is None:
        seconds = float(os.getenv("NATIVE_DIALOG_PULSE_SEC", "12"))

    total = pulse_cryptopro_access(seconds)
    deadline = time.time() + max(0.0, seconds * 0.5)
    patterns = _patterns()
    button_labels = _button_labels()
    while time.time() < deadline:
        total += _handle_gosplugin_qt_dialogs()
        total += _handle_access_confirmation_pywinauto()
        total += _scan_other_dialogs(patterns, button_labels)
        time.sleep(0.2)
    return total


def pulse_gosplugin_dialogs(seconds: float | None = None) -> int:
    """Закрывает Qt-окна Госплагин «Подтверждение» (кнопка OK через UIA)."""
    if sys.platform != "win32" or not _enabled():
        return 0

    if seconds is None:
        seconds = float(os.getenv("GOSPLUGIN_PULSE_SEC", "30"))

    total = 0
    deadline = time.time() + seconds
    poll = float(os.getenv("GOSPLUGIN_POLL_SEC", "0.2"))
    appear_grace = float(os.getenv("NATIVE_DIALOG_APPEAR_GRACE_SEC", "5"))
    empty_since = time.time()

    while time.time() < deadline:
        remaining = _gosplugin_qt_dialogs_remain()
        if remaining == 0:
            if total > 0:
                log_info(
                    f"Госплагин: все окна «Подтверждение» закрыты ({total} кликов)",
                    stage="native_dialog",
                )
                break
            if time.time() - empty_since >= appear_grace:
                break
            time.sleep(poll)
            continue
        empty_since = time.time()

        if remaining > 1:
            log_info(
                f"Госплагин: обнаружено окон «Подтверждение»: {remaining}",
                stage="native_dialog",
            )

        total += _handle_gosplugin_qt_dialogs()
        time.sleep(poll)

    if _gosplugin_qt_dialogs_remain() > 0:
        log_warning(
            f"Госплагин: остались незакрытые окна ({_gosplugin_qt_dialogs_remain()} шт.)",
            stage="native_dialog",
        )

    return total

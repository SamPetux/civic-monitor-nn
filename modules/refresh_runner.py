"""
Фоновый запуск пайплайна обновления данных из UI.

Состояние:
    data/refresh.lock        — pid + timestamp текущего процесса
    data/refresh.log         — stdout/stderr процесса
    data/refresh.result      — флажок 'done' / 'failed' от последнего прогона.
                                Создаётся внутри shell-цепочки в самом конце,
                                чтобы UI знал, что прогон завершился, даже
                                если PID уже сдох (а лок ещё не подчищен).

Логика:
    is_running       = есть лок И PID жив И флажка result ещё нет
    last_result      = "done" | "failed" | None — читается из файла-флажка
    clear_last_result() — UI вызывает после показа результата, чтобы
                         флажок не висел вечно
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from modules.config import DATA_DIR

LOCK_PATH   = DATA_DIR / "refresh.lock"
LOG_PATH    = DATA_DIR / "refresh.log"
RESULT_PATH = DATA_DIR / "refresh.result"

RESULT_DONE   = "done"
RESULT_FAILED = "failed"


@dataclass
class RefreshStatus:
    is_running: bool
    pid: int | None
    started_at: float | None
    log_tail: str
    last_result: str | None     # "done" / "failed" / None


# ----------------------------------------------------------------------
def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_lock() -> tuple[int | None, float | None]:
    if not LOCK_PATH.exists():
        return None, None
    try:
        text = LOCK_PATH.read_text().strip().split()
        return int(text[0]), float(text[1])
    except (ValueError, IndexError):
        return None, None


def _clear_lock() -> None:
    try:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()
    except OSError:
        pass


def _read_log_tail(n_lines: int = 200) -> str:
    if not LOG_PATH.exists():
        return ""
    try:
        text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
        return "\n".join(text.splitlines()[-n_lines:])
    except OSError:
        return ""


def _read_result() -> str | None:
    if not RESULT_PATH.exists():
        return None
    try:
        v = RESULT_PATH.read_text(encoding="utf-8").strip()
        return v if v in (RESULT_DONE, RESULT_FAILED) else None
    except OSError:
        return None


def clear_last_result() -> None:
    """UI зовёт после показа итогов, чтобы плашка ушла."""
    try:
        if RESULT_PATH.exists():
            RESULT_PATH.unlink()
    except OSError:
        pass


# ----------------------------------------------------------------------
def get_status() -> RefreshStatus:
    pid, started_at = _read_lock()
    last_result = _read_result()
    log_tail = _read_log_tail()

    process_alive = bool(pid and _is_alive(pid))

    # Когда процесс закончился — НЕ держим is_running, даже если pid ещё
    # формально живой 1-2 секунды (на shell-cleanup).
    is_running = process_alive and last_result is None

    if pid and (not process_alive or last_result is not None):
        _clear_lock()

    return RefreshStatus(
        is_running=is_running,
        pid=pid if is_running else None,
        started_at=started_at if is_running else None,
        log_tail=log_tail,
        last_result=last_result,
    )


def force_clear() -> None:
    """Жёсткий сброс — для аварийной кнопки в UI."""
    pid, _ = _read_lock()
    if pid and _is_alive(pid):
        try:
            os.killpg(os.getpgid(pid), 15)
        except (ProcessLookupError, PermissionError):
            pass
    _clear_lock()
    clear_last_result()


# ----------------------------------------------------------------------
def start_refresh(
    days: int | None = None,
    hours: int | None = None,
    max_posts: int = 50,
    skip_topics: bool = True,
    skip_sentiment: bool = True,   # NEW
    skip_bursts: bool = False,
) -> tuple[bool, str]:
    """
    Запустить полный пайплайн в фоне.

    Граница парсинга — ровно одна из:
        days   — за сколько последних суток парсить
        hours  — за сколько последних часов
    """
    status = get_status()
    if status.is_running:
        return False, f"Уже идёт обновление (pid={status.pid})"

    # Чистый старт
    _clear_lock()
    clear_last_result()

    if hours is not None:
        parse_window = f"--hours {hours}"
    elif days is not None:
        parse_window = f"--days {days}"
    else:
        parse_window = "--days 1"

    py = sys.executable

    # Pre-flight: убеждаемся, что parse.py поддерживает новые флаги
    check_cmd = f"{shlex.quote(py)} parse.py --help"
    try:
        help_out = subprocess.check_output(
            ["/bin/bash", "-c", check_cmd],
            cwd=Path(__file__).resolve().parent.parent,
            stderr=subprocess.STDOUT, text=True, timeout=10,
        )
        if "--hours" not in help_out and "--since" not in help_out:
            return False, (
                "У вас старая версия parse.py — она не понимает "
                "--hours/--since. Замените parse.py на новую версию."
            )
    except subprocess.SubprocessError:
        pass

    cmd_parts = [
        f"{shlex.quote(py)} parse.py {parse_window} --max-posts {max_posts}",
        f"{shlex.quote(py)} parse.py --enrich-users",
    ]
    if not skip_sentiment:
        cmd_parts.append(f"{shlex.quote(py)} analyze_sentiment.py")
    cmd_parts.append(f"{shlex.quote(py)} geocode_posts.py")
    if not skip_topics:
        cmd_parts.append(f"{shlex.quote(py)} analyze_topics.py --reset")
    if not skip_bursts:
        cmd_parts.append(f"{shlex.quote(py)} detect_bursts.py --reset")

    pipeline = " && ".join(cmd_parts)
    result_path_q = shlex.quote(str(RESULT_PATH))

    # ВАЖНО: в самом конце цепочки гарантированно записываем флажок результата.
    # ( pipeline && echo done > result ) || echo failed > result
    wrapped_cmd = (
        f"( ({pipeline}) "
        f"&& echo {RESULT_DONE} > {result_path_q} ) "
        f"|| echo {RESULT_FAILED} > {result_path_q}"
    )

    LOG_PATH.write_text(
        f"$ {pipeline}\n"
        f"--- started at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n",
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        ["/bin/bash", "-c", wrapped_cmd],
        stdout=open(LOG_PATH, "ab"),
        stderr=subprocess.STDOUT,
        cwd=Path(__file__).resolve().parent.parent,
        start_new_session=True,
    )
    LOCK_PATH.write_text(f"{proc.pid} {time.time()}", encoding="utf-8")
    return True, f"Запущено (pid={proc.pid})"


def cancel_refresh() -> tuple[bool, str]:
    pid, _ = _read_lock()
    if not pid or not _is_alive(pid):
        _clear_lock()
        return False, "Нет активного процесса"
    try:
        os.killpg(os.getpgid(pid), 15)
        time.sleep(0.5)
        if _is_alive(pid):
            os.killpg(os.getpgid(pid), 9)
    except ProcessLookupError:
        pass
    finally:
        _clear_lock()
        # Помечаем результат как failed, чтобы UI понял
        try:
            RESULT_PATH.write_text(RESULT_FAILED, encoding="utf-8")
        except OSError:
            pass
    return True, f"Остановлен pid={pid}"
"""Фоновый запуск раннеров со сбором логов и историей запусков.

Каждый раннер выполняется в отдельном потоке со своим event loop
(``asyncio.run``) — так же, как при самостоятельном запуске из cron.
Синхронные вызовы внутри раннеров (requests, Gemini) не блокируют
event loop веб-приложения.

Раннеры глотают исключения (``except Exception: logger.error(...)``),
поэтому итоговый статус определяется по наличию записей уровня ERROR,
попавших в лог за время выполнения.
"""
import asyncio
import contextvars
import datetime
import json
import logging
import os
import threading
import uuid
from collections import deque

from config import BASE_STORAGE_PATH
from webapp.registry import get_generator

logger = logging.getLogger(__name__)

RUNS_LOG_PATH = os.path.join(BASE_STORAGE_PATH, "webapp", "runs.jsonl")
MAX_LOG_LINES = 500       # предел строк лога, хранимых для одного запуска
PERSIST_LOG_TAIL = 200    # сколько строк лога сохранять в runs.jsonl
HISTORY_LIMIT = 200       # сколько завершённых запусков держать в истории
RUN_TIMEOUT = 2 * 60 * 60  # секунд на один запуск (MidJourney/видео бывают долгими)

current_run_id = contextvars.ContextVar("utriskra_run_id", default=None)

TRIGGER_TITLES = {"manual": "вручную", "schedule": "по расписанию"}
STATUS_TITLES = {"success": "успех", "error": "ошибка", "running": "выполняется"}


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _is_gc_noise(record) -> bool:
    """«Future/Task exception was never retrieved» от asyncio — не сбой запуска.

    Так asyncio при сборке мусора сообщает о брошенной внутренней задаче. После
    тайм-аута отправки в Telegram такую оставляет aiohttp (обрыв загрузки фото), а
    публикатор уже повторил отправку и пост вышел. Настоящий сбой раннера приходит
    исключением или собственной записью ERROR.
    """
    return record.name == "asyncio" and "exception was never retrieved" in record.getMessage()


class LogCaptureHandler(logging.Handler):
    """Пишет записи логов в буфер запуска, активного в текущем контексте."""

    def __init__(self, manager):
        super().__init__(level=logging.INFO)
        self._manager = manager
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record):
        run_id = current_run_id.get()
        if run_id is None:
            return
        run = self._manager.runs.get(run_id)
        if run is None or run["status"] != "running":
            return
        try:
            if len(run["logs"]) < MAX_LOG_LINES:
                run["logs"].append(self.format(record))
            elif len(run["logs"]) == MAX_LOG_LINES:
                run["logs"].append("… лог обрезан …")
            if record.levelno >= logging.ERROR and not _is_gc_noise(record):
                run["had_error"] = True
        except Exception:  # логирование не должно ломать запуск
            self.handleError(record)


class TaskManager:
    def __init__(self):
        self.runs = {}                          # run_id -> запись запуска
        self.history = deque()                  # завершённые и активные, старые в начале
        self.active = {}                        # ключ генератора -> run_id
        self._tasks = set()
        self._lock = threading.Lock()
        self._load_history()

    # ------------------------------------------------------------------ setup

    def install_log_handler(self):
        logging.getLogger().addHandler(LogCaptureHandler(self))

    def _load_history(self):
        try:
            with open(RUNS_LOG_PATH, encoding="utf-8") as file:
                lines = file.readlines()[-HISTORY_LIMIT:]
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("Не удалось прочитать %s: %s", RUNS_LOG_PATH, exc)
            return
        for line in lines:
            try:
                run = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run.get("run_id") and run.get("status") in ("success", "error"):
                self.runs[run["run_id"]] = run
                self.history.append(run)

    def _append_runs_log(self, run):
        persisted = dict(run, logs=run["logs"][-PERSIST_LOG_TAIL:])
        try:
            os.makedirs(os.path.dirname(RUNS_LOG_PATH), exist_ok=True)
            with open(RUNS_LOG_PATH, "a", encoding="utf-8") as file:
                file.write(json.dumps(persisted, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Не удалось дописать %s: %s", RUNS_LOG_PATH, exc)

    # ------------------------------------------------------------------- runs

    def start(self, key, trigger="manual"):
        """Стартует генератор в фоне; возвращает run_id.

        Вызывать только из потока с работающим event loop.
        """
        generator = get_generator(key)
        if generator is None:
            raise KeyError(f"Неизвестный генератор: {key}")
        with self._lock:
            if key in self.active:
                raise RuntimeError(f"«{generator.title}» уже выполняется")
            run = {
                "run_id": uuid.uuid4().hex[:12],
                "key": key,
                "title": generator.title,
                "trigger": trigger,
                "status": "running",
                "started_at": _utc_now().isoformat(timespec="seconds"),
                "finished_at": None,
                "duration": None,
                "error": None,
                "had_error": False,
                "logs": [],
            }
            self.runs[run["run_id"]] = run
            self.active[key] = run["run_id"]
            self.history.append(run)
            while len(self.history) > HISTORY_LIMIT:
                dropped = self.history.popleft()
                if dropped["status"] != "running":
                    self.runs.pop(dropped["run_id"], None)
        logger.info("Запуск «%s» (%s), run_id=%s", generator.title,
                    TRIGGER_TITLES.get(trigger, trigger), run["run_id"])
        task = asyncio.get_running_loop().create_task(self._execute(run, generator))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run["run_id"]

    @staticmethod
    def _run_blocking(generator):
        from core.pipeline import run_job_sync
        run_job_sync(generator.key)

    async def _execute(self, run, generator):
        started = _utc_now()
        token = current_run_id.set(run["run_id"])
        try:
            await asyncio.wait_for(asyncio.to_thread(self._run_blocking, generator),
                                   timeout=RUN_TIMEOUT)
        except asyncio.TimeoutError:
            run["error"] = f"Превышен лимит времени ({RUN_TIMEOUT // 3600} ч)"
            run["had_error"] = True
            logger.error("Запуск «%s» прерван по таймауту", generator.title)
        except Exception as exc:
            run["error"] = f"{type(exc).__name__}: {exc}"
            run["had_error"] = True
            logger.exception("Ошибка запуска «%s»", generator.title)
        finally:
            current_run_id.reset(token)
            with self._lock:
                run["status"] = "error" if run["had_error"] else "success"
                run["finished_at"] = _utc_now().isoformat(timespec="seconds")
                run["duration"] = round((_utc_now() - started).total_seconds(), 1)
                if run["had_error"] and not run["error"]:
                    run["error"] = "В логе есть ошибки (см. лог запуска)"
                self.active.pop(run["key"], None)
            logger.info("Запуск «%s» завершён: %s за %s с",
                        generator.title, run["status"], run["duration"])
            self._append_runs_log(run)

    # ---------------------------------------------------------------- queries

    @staticmethod
    def summary(run):
        return {k: v for k, v in run.items() if k != "logs"}

    def is_running(self, key):
        return key in self.active

    def last_run_for(self, key):
        with self._lock:
            for run in reversed(self.history):
                if run["key"] == key:
                    return self.summary(run)
        return None

    def recent(self, limit=20):
        with self._lock:
            runs = list(self.history)[-limit:]
        return [self.summary(run) for run in reversed(runs)]

    def get_logs(self, run_id):
        run = self.runs.get(run_id)
        if run is None:
            return None
        return "\n".join(list(run["logs"]))

    def job_logs(self, key, run_count=3):
        """Логи последних N запусков задачи (старые сверху), собранные из истории.

        История переживает рестарты (runs.jsonl); лог одного запуска хранится
        с хвостом до PERSIST_LOG_TAIL строк.
        """
        with self._lock:
            runs = [run for run in self.history if run["key"] == key][-run_count:]
        lines = []
        for run in runs:
            lines.append(f"═════ запуск {run['run_id']} · "
                         f"{TRIGGER_TITLES.get(run['trigger'], run['trigger'])} · "
                         f"{run['started_at']} ═════")
            lines.extend(list(run["logs"]))
            if run["status"] == "running":
                lines.append("───── выполняется… ─────")
            else:
                error_note = f" — {run['error']}" if run.get("error") else ""
                lines.append(f"───── {STATUS_TITLES.get(run['status'], run['status'])} "
                             f"за {run['duration']} с{error_note} ─────")
            lines.append("")
        return lines

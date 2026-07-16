"""Хранение расписания генераций в JSON (storage/webapp/schedule.json)."""
import json
import logging
import os
import threading

from config import BASE_STORAGE_PATH
from webapp.registry import get_generators

logger = logging.getLogger(__name__)

WEBAPP_STORAGE = os.path.join(BASE_STORAGE_PATH, "webapp")
SCHEDULE_PATH = os.path.join(WEBAPP_STORAGE, "schedule.json")
_lock = threading.Lock()


def _defaults():
    # Все генераторы выключены по умолчанию: установка панели не должна сама
    # начать публиковать в канал — нужные включаются явно в интерфейсе.
    return {
        g.key: {"enabled": False, "hour": g.default_hour, "minute": g.default_minute}
        for g in get_generators()
    }


def _sanitize(entry, default):
    enabled = bool(entry.get("enabled", default["enabled"]))
    try:
        hour = int(entry.get("hour", default["hour"]))
        minute = int(entry.get("minute", default["minute"]))
    except (TypeError, ValueError):
        hour, minute = default["hour"], default["minute"]
    if not 0 <= hour <= 23:
        hour = default["hour"]
    if not 0 <= minute <= 59:
        minute = default["minute"]
    return {"enabled": enabled, "hour": hour, "minute": minute}


def load_schedule():
    """Возвращает расписание всех генераторов: сохранённое поверх значений по умолчанию."""
    schedule = _defaults()
    with _lock:
        try:
            with open(SCHEDULE_PATH, encoding="utf-8") as file:
                stored = json.load(file)
        except FileNotFoundError:
            return schedule
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Не удалось прочитать %s: %s — использую значения по умолчанию",
                           SCHEDULE_PATH, exc)
            return schedule
    for key, entry in stored.items():
        if key in schedule and isinstance(entry, dict):
            schedule[key] = _sanitize(entry, schedule[key])
    return schedule


def set_entry(key, enabled, hour, minute):
    """Сохраняет настройку одного генератора (атомарная запись файла)."""
    schedule = load_schedule()
    schedule[key] = {"enabled": bool(enabled), "hour": int(hour), "minute": int(minute)}
    with _lock:
        os.makedirs(WEBAPP_STORAGE, exist_ok=True)
        tmp_path = SCHEDULE_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(schedule, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, SCHEDULE_PATH)
    return schedule[key]

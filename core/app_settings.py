"""Runtime-настройки панели (storage/webapp/settings.json).

Сейчас здесь живёт один флаг — debug_publish: публиковать через отладочного
бота в отладочный чат (DEBUG_TELEGRAM_TOKEN / DEBUG_TARGET_CHAT_ID из .env).
"""
import json
import logging
import os
import threading

from config import BASE_STORAGE_PATH

logger = logging.getLogger(__name__)

SETTINGS_PATH = os.path.join(BASE_STORAGE_PATH, "webapp", "settings.json")
_lock = threading.Lock()


def load() -> dict:
    with _lock:
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Не удалось прочитать %s: %s", SETTINGS_PATH, exc)
            return {}


def set_value(key: str, value):
    settings = load()
    settings[key] = value
    with _lock:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        tmp_path = SETTINGS_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, SETTINGS_PATH)


def debug_publish_enabled() -> bool:
    return bool(load().get("debug_publish", False))

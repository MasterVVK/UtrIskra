"""providers.json: инстансы LLM/image-провайдеров и цепочка fallback.

Секреты в конфиге не хранятся — только имена env-переменных (keys_env,
api_key_env). Первичный файл генерируется из текущих значений .env.
"""
import json
import logging
import os
import threading

from config import (BASE_STORAGE_PATH, QWEN_API_URL, ZIMAGE_API_URL, ERNIE_API_URL,
                    HIDREAM_API_URL, QWEN_CHAT_API_URL, FALLBACK_LLM_URL, FALLBACK_LLM_MODEL)

logger = logging.getLogger(__name__)

PROVIDERS_PATH = os.path.join(BASE_STORAGE_PATH, "webapp", "providers.json")
_lock = threading.Lock()
_cache = {"mtime": None, "data": None}


def _aspect(default="16:9"):
    return {"key": "aspect_ratio", "label": "Соотношение сторон", "kind": "choice",
            "choices": ["1:1", "16:9", "9:16", "4:3", "3:4"], "default": default}


def _defaults():
    return {
        "llm": {
            "gemini": {"type": "gemini", "model": "gemini-3.5-flash",
                       "keys_env": "GEMINI_API_KEYS", "proxy": True},
            "qwen-fallback": {"type": "openai", "base_url": FALLBACK_LLM_URL,
                              "model": FALLBACK_LLM_MODEL,
                              "api_key_env": "FALLBACK_LLM_KEY", "timeout": 600},
        },
        "llm_chain": ["gemini", "qwen-fallback"],
        "image": {
            "stability": {"type": "stability"},
            "kandinsky": {"type": "kandinsky"},
            "dalle": {"type": "dalle"},
            "flux": {"type": "flux", "endpoint": "flux-pro-1.1-ultra"},
            "yandex": {"type": "yandex"},
            "gemini_image": {"type": "gemini_image"},
            "midjourney": {"type": "midjourney"},
            "qwen_chat": {"type": "qwen_chat", "base_url": QWEN_CHAT_API_URL},
            "qwen": {"type": "local_task", "base_url": QWEN_API_URL, "params": [
                _aspect(),
                {"key": "negative_prompt", "label": "Негативный промпт", "kind": "str", "default": ""},
                {"key": "num_inference_steps", "label": "Шаги", "kind": "int",
                 "default": 50, "min": 1, "max": 100},
                {"key": "cfg_scale", "label": "CFG", "kind": "float",
                 "default": 4.0, "min": 1, "max": 20},
            ]},
            "zimage": {"type": "local_task", "base_url": ZIMAGE_API_URL, "params": [
                {"key": "model", "label": "Модель", "kind": "str", "default": "base"},
                _aspect(),
                {"key": "negative_prompt", "label": "Негативный промпт", "kind": "str", "default": ""},
                {"key": "num_inference_steps", "label": "Шаги", "kind": "int",
                 "default": 30, "min": 1, "max": 100},
                {"key": "guidance_scale", "label": "Guidance", "kind": "float",
                 "default": 5.0, "min": 1, "max": 20},
            ]},
            "ernie": {"type": "local_task", "base_url": ERNIE_API_URL, "params": [
                {"key": "model", "label": "Модель", "kind": "str", "default": "sft"},
                _aspect(),
                {"key": "negative_prompt", "label": "Негативный промпт", "kind": "str", "default": ""},
                {"key": "num_inference_steps", "label": "Шаги", "kind": "int",
                 "default": 100, "min": 1, "max": 200},
                {"key": "guidance_scale", "label": "Guidance", "kind": "float",
                 "default": 4.0, "min": 1, "max": 20},
                {"key": "use_pe", "label": "Prompt enhancement", "kind": "bool", "default": True},
            ]},
            "hidream": {"type": "local_task", "base_url": HIDREAM_API_URL, "params": [
                _aspect(),
                {"key": "use_pe", "label": "Prompt enhancement", "kind": "bool", "default": True},
            ]},
        },
    }


def load_providers() -> dict:
    """Читает providers.json; при первом обращении создаёт его из дефолтов."""
    with _lock:
        try:
            mtime = os.path.getmtime(PROVIDERS_PATH)
            if _cache["mtime"] == mtime and _cache["data"] is not None:
                return _cache["data"]
            with open(PROVIDERS_PATH, encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            data = _defaults()
            _write(data)
            mtime = os.path.getmtime(PROVIDERS_PATH)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Не удалось прочитать %s: %s — использую дефолты", PROVIDERS_PATH, exc)
            return _defaults()
        for section in ("llm", "image"):
            data.setdefault(section, {})
        data.setdefault("llm_chain", list(data["llm"].keys())[:1])
        # домердж инстансов, появившихся в новых версиях кода: каждый дефолт
        # засевается ровно один раз (метка _seeded), поэтому удалённые
        # пользователем инстансы не воскресают при следующей загрузке
        defaults = _defaults()
        seeded = set(data.get("_seeded") or [])
        added, marked = [], False
        for section in ("llm", "image"):
            for name, config in defaults[section].items():
                if name in seeded:
                    continue
                if name not in data[section]:
                    data[section][name] = config
                    added.append(name)
                seeded.add(name)
                marked = True
        if marked:
            data["_seeded"] = sorted(seeded)
            if added:
                logger.info("providers.json: добавлены новые дефолтные инстансы: %s", added)
            _write(data)
        else:
            _cache.update(mtime=mtime, data=data)
        return data


def _write(data):
    os.makedirs(os.path.dirname(PROVIDERS_PATH), exist_ok=True)
    tmp_path = PROVIDERS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(tmp_path, PROVIDERS_PATH)
    _cache.update(mtime=os.path.getmtime(PROVIDERS_PATH), data=data)


def get_llm_config(name: str) -> dict:
    config = load_providers()["llm"].get(name)
    if config is None:
        raise KeyError(f"LLM-провайдер «{name}» не найден в providers.json")
    return config


def get_image_config(name: str) -> dict:
    config = load_providers()["image"].get(name)
    if config is None:
        raise KeyError(f"Image-провайдер «{name}» не найден в providers.json")
    return config


def llm_chain() -> list:
    return list(load_providers().get("llm_chain", []))


def save_provider(kind: str, name: str, config: dict):
    if kind not in ("llm", "image"):
        raise ValueError(f"Неизвестный вид провайдера: {kind}")
    data = load_providers()
    with _lock:
        data[kind][name] = config
        _write(data)


def save_llm_chain(chain: list):
    data = load_providers()
    unknown = [name for name in chain if name not in data["llm"]]
    if unknown:
        raise ValueError(f"В цепочке неизвестные провайдеры: {unknown}")
    with _lock:
        data["llm_chain"] = list(chain)
        _write(data)

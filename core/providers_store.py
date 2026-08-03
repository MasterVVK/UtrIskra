"""providers.json: инстансы LLM/image-провайдеров и цепочка fallback.

Секреты в конфиге не хранятся — только имена env-переменных (keys_env,
api_key_env). Первичный файл генерируется из текущих значений .env.
"""
import json
import logging
import os
import threading

from config import (BASE_STORAGE_PATH, IMAGES_API_URL, QWEN_CHAT_API_URL,
                    FALLBACK_LLM_URL, FALLBACK_LLM_MODEL)

logger = logging.getLogger(__name__)

PROVIDERS_PATH = os.path.join(BASE_STORAGE_PATH, "webapp", "providers.json")
_lock = threading.Lock()
_cache = {"mtime": None, "data": None}


def _aspect(choices=("16:9", "1:1", "4:3", "3:4", "9:16"), default="16:9"):
    # Набор пресетов у каждой модели свой — сверяется с GET /api/v1/resolutions
    # шлюза: значение вне списка он отвергает, а не подгоняет.
    return {"key": "aspect_ratio", "label": "Соотношение сторон", "kind": "choice",
            "choices": list(choices), "default": default}


def _negative():
    return {"key": "negative_prompt", "label": "Негативный промпт", "kind": "str", "default": ""}


def _steps(default, maximum=100):
    return {"key": "num_inference_steps", "label": "Шаги", "kind": "int",
            "default": default, "min": 1, "max": maximum}


def _guidance(default, label="CFG"):
    return {"key": "guidance_scale", "label": label, "kind": "float",
            "default": default, "min": 0, "max": 20}


def _use_pe(default):
    return {"key": "use_pe", "label": "Улучшение промпта (внешняя LLM шлюза)",
            "kind": "bool", "default": default}


def _images_api(model, params):
    """Инстанс единого шлюза images-api: общий адрес и ключ, своя модель."""
    return {"type": "images_api", "base_url": IMAGES_API_URL,
            "api_key_env": "IMAGES_API_KEY", "model": model, "params": params}


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
            # Четыре инстанса одного шлюза: имена сохранены с времён отдельных
            # сервисов, чтобы задачи и их расписание не переезжали.
            "qwen": _images_api("qwen-image", [
                _aspect(),
                _negative(),
                _steps(50),
                _guidance(4.0, "CFG (true_cfg_scale)"),
                _use_pe(False),
            ]),
            "zimage": _images_api("z-image-base", [
                {"key": "model", "label": "Модель (turbo: 9 шагов, CFG 0)", "kind": "choice",
                 "choices": ["z-image-base", "z-image-turbo"], "default": "z-image-base"},
                _aspect(),
                _negative(),
                _steps(30),
                _guidance(5.0),
                _use_pe(False),
            ]),
            "ernie": _images_api("ernie-image", [
                {"key": "model", "label": "Модель (turbo: 8 шагов, CFG 1)", "kind": "choice",
                 "choices": ["ernie-image", "ernie-image-turbo"], "default": "ernie-image"},
                _aspect(("16:9", "1:1", "3:2", "2:3", "4:3", "3:4", "9:16")),
                _negative(),
                _steps(100),
                _guidance(4.0),
                _use_pe(True),
            ]),
            # negative_prompt у hidream нет намеренно: модель его не принимает,
            # непустое значение шлюз отвергает с 422.
            "hidream": _images_api("hidream-o1", [
                _aspect(("16:9", "1:1", "21:9", "9:21", "3:2", "2:3",
                         "4:3", "3:4", "9:7", "7:9", "9:16")),
                _steps(50),
                _guidance(5.0),
                {"key": "shift", "label": "Shift", "kind": "float",
                 "default": 3.0, "min": 0, "max": 20},
                {"key": "scheduler", "label": "Планировщик", "kind": "choice",
                 "choices": ["default", "flow_match", "flash"], "default": "default"},
                _use_pe(True),
            ]),
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

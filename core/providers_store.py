"""providers.json: инстансы LLM/image-провайдеров и цепочка fallback.

Секреты в конфиге не хранятся — только имена env-переменных (keys_env,
api_key_env). Первичный файл генерируется из текущих значений .env.
"""
import json
import logging
import os
import threading

from config import (BASE_STORAGE_PATH, IMAGES_API_URL, QWEN_CHAT_API_URL,
                    FALLBACK_LLM_URL, FALLBACK_LLM_MODEL, FALLBACK_LLM_HEALTH_URL)

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
                              "api_key_env": "FALLBACK_LLM_KEY",
                              # Qwen4 с рассуждением отвечает за 2–4 мин на промпт в 20–30 тыс.
                              # знаков (замер 17.11.2026). Дольше ~5 мин — значит, на аккаунте
                              # суточный лимит: ждать бесполезно, а повтор кулдаунит пул.
                              "timeout": 330,
                              # /health пула Qwen2API: при free == 0 запрос не шлётся.
                              "health_url": FALLBACK_LLM_HEALTH_URL,
                              # Вечерняя заготовка: включается флагом "pregen": true вместе
                              # с путями pregen_trigger_file / pregen_done_file (протокол с
                              # другим клиентом квоты — см. core/prompt_batches.py).
                              "pregen": False},
            # Claude через официальный SDK (ключ ANTHROPIC_API_KEY в .env); в цепочке
            # по умолчанию — второй, после Qwen4.
            "opus": {"type": "anthropic", "model": "claude-opus-5-5", "effort": "high"},
        },
        # Порядок синхронных попыток: Claude Opus, Qwen4 с рассуждением (Qwen2API), Gemini.
        # Qwen4 по слепому сравнению пишет промпты лучше всех, но его суточная квота общая
        # с другими клиентами сервиса и к утру выбрана. Поэтому он пишет тексты вечером,
        # заранее (флаг "pregen" у qwen-fallback, core/prompt_batches.py), а пропуски
        # закрывает пакет Opus (флаг "batch"; действует, только когда opus первый в цепочке).
        "llm_chain": ["opus", "qwen-fallback", "gemini"],
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
            # Qwen-Image 2.1 (преемник 2512): родное разрешение 2K, CFG по умолчанию
            # выключен — negative_prompt действует только при guidance_scale > 1 и
            # удваивает время. Варианты одного чекпойнта отличаются только тем, где
            # лежат веса: -full — всё на большой карте узла dml, -bf16 — полные веса
            # на 3090 (17.7 ГБ), без суффикса — веса в fp8 (10.7 ГБ). Качество у
            # -full и -bf16 одинаковое и лучшее; задача просит его первым, а если
            # шлюз не может запустить модель из-за памяти или узла, провайдер сам
            # переходит к следующей по fallback_models. У turbo шаги (8) зашиты.
            "qwen": dict(_images_api("qwen-image-2.1-full", [
                {"key": "model", "label": "Модель (turbo: шаги = 8, без CFG и негатива)",
                 "kind": "choice",
                 "choices": ["qwen-image-2.1-full", "qwen-image-2.1-bf16",
                             "qwen-image-2.1", "qwen-image-2.1-turbo"],
                 "default": "qwen-image-2.1-full"},
                _aspect(("16:9", "1:1", "3:2", "2:3", "4:3", "3:4", "9:16")),
                _negative(),
                _steps(40),
                _guidance(1.0, "CFG (1 = выключен; больше 1 включает негативный промпт)"),
                _use_pe(False),
            ]), fallback_models={"qwen-image-2.1-full": "qwen-image-2.1-bf16",
                                 "qwen-image-2.1-bf16": "qwen-image-2.1"}),
            # MOSS-Image (OpenMOSS, Apache-2.0): ~2 Мп, сильна в тексте на картинке,
            # включая многострочный. CFG включён при любом guidance_scale, кроме 1.0;
            # пустой negative допустим (и рекомендован авторами для длинных промптов).
            # -full — тот же чекпойнт целиком на большой карте узла dml; при отказе по
            # ресурсам провайдер спускается к moss-image (энкодер в RAM узла с 3090).
            "moss": dict(_images_api("moss-image-full", [
                {"key": "model", "label": "Модель", "kind": "choice",
                 "choices": ["moss-image-full", "moss-image"], "default": "moss-image-full"},
                _aspect(("16:9", "1:1", "3:2", "2:3", "4:3", "3:4", "9:16")),
                _negative(),
                _steps(50),
                _guidance(3.0, "CFG (рекомендуется 3–6)"),
                _use_pe(False),
            ]), fallback_models={"moss-image-full": "moss-image"}),
            # MiniMax-H3-Image (только узел dml): 16.8 Мп в 16:9 (5472×3072), ~6.5 мин,
            # пик ~68 ГБ. Шаги (6) и guidance зашиты в чекпойнт, negative_prompt нет —
            # из параметров только соотношение сторон. Запасной модели нет; днём карту
            # занимают модели ollama, поэтому при vram_unavailable задача ставится
            # заново до 5 раз (до часа ожидания в сумме).
            "minimax": dict(_images_api("minimax-h3-image", [
                _aspect(("16:9", "21:9", "3:2", "4:3", "1:1", "3:4", "2:3", "9:16", "9:21")),
            ]), timeout=2400, vram_wait_rounds=5),
            # -full — Z-Image Base целиком на большой карте узла dml; при отказе по
            # ресурсам провайдер спускается к z-image-base (энкодер в RAM узла с 3090).
            "zimage": dict(_images_api("z-image-base-full", [
                {"key": "model", "label": "Модель (turbo: 9 шагов, CFG 0)", "kind": "choice",
                 "choices": ["z-image-base-full", "z-image-base", "z-image-turbo"],
                 "default": "z-image-base-full"},
                _aspect(),
                _negative(),
                _steps(30),
                _guidance(5.0),
                _use_pe(False),
            ]), fallback_models={"z-image-base-full": "z-image-base"}),
            # ERNIE-Image SFT: -full — тот же чекпойнт целиком на большой карте узла
            # dml; на 3090 (ernie-image) энкодер живёт в RAM, и при занятой соседями
            # карте задача не стартует. Задача просит -full, при отказе по ресурсам
            # провайдер спускается к ernie-image.
            "ernie": dict(_images_api("ernie-image-full", [
                {"key": "model", "label": "Модель (turbo: 8 шагов, CFG 1)", "kind": "choice",
                 "choices": ["ernie-image-full", "ernie-image", "ernie-image-turbo"],
                 "default": "ernie-image-full"},
                _aspect(("16:9", "1:1", "3:2", "2:3", "4:3", "3:4", "9:16")),
                _negative(),
                _steps(100),
                _guidance(4.0),
                _use_pe(False),
            ]), fallback_models={"ernie-image-full": "ernie-image"}),
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

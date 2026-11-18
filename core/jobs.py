"""jobs.json: задачи генерации (что и как генерировать/публиковать).

Расписание (вкл/выкл, время) живёт отдельно — в storage/webapp/schedule.json,
это runtime-состояние; здесь — определения задач. Первичный файл генерируется
со значениями, воспроизводящими поведение старых раннеров 1:1.
"""
import json
import logging
import os
import threading

from config import BASE_STORAGE_PATH

logger = logging.getLogger(__name__)

JOBS_PATH = os.path.join(BASE_STORAGE_PATH, "webapp", "jobs.json")
_lock = threading.Lock()
_cache = {"mtime": None, "data": None}


def _image_job(title, prefix, prompt_file, letter, image_provider, image_params,
               hour, minute, *, temperature=0.7, max_theme=10, max_category=14,
               retries=0, note=""):
    return {
        "title": title, "pipeline": "image", "media": "image",
        "file_prefix": prefix, "extra_prefixes": [],
        "prompt_file": prompt_file,
        "llm": {"provider": None, "temperature": temperature,
                "max_theme": max_theme, "max_category": max_category},
        "image": {"provider": image_provider, "params": image_params},
        "watermark": {"enabled": True, "letter": letter},
        "publish": {"chat_id": None, "retries": retries},
        "default_hour": hour, "default_minute": minute,
        "note": note,
    }


def _video_job(title, prefix, extra, prompt_file, letter, hour, minute,
               *, temperature=1.0, note=""):
    return {
        "title": title, "pipeline": "midjourney_video", "media": "video",
        "file_prefix": prefix, "extra_prefixes": extra,
        "prompt_file": prompt_file,
        "llm": {"provider": None, "temperature": temperature,
                "max_theme": 10, "max_category": 14},
        "video": {"aspect_ratio": "16:9",
                  "prompt": "gentle movement, cinematic camera motion",
                  "motion": "high", "task_type": "image-to-video-hd"},
        "watermark": {"enabled": True, "letter": letter},
        "publish": {"chat_id": None, "retries": 0, "debug": False},
        "default_hour": hour, "default_minute": minute,
        "note": note,
    }


def _default_jobs():
    return {
        "stability": _image_job(
            "Stability AI", "daily_story", "daily_runner.txt", "S", "stability",
            {"aspect_ratio": "16:9", "negative_prompt": "low quality, watermark",
             "output_format": "png"}, 7, 0),
        "kandinsky": _image_job(
            "Kandinsky", "kandinsky_story", "kandinsky_runner.txt", "K", "kandinsky",
            {"width": 1344, "height": 768}, 8, 0, temperature=1.0),
        "midjourney": _image_job(
            "MidJourney", "midjourney_story", "midjourney_runner.txt", "M", "midjourney",
            {"aspect_ratio": "16:9", "speed": "relaxed", "crop_position": "1"},
            9, 0, temperature=1.0),
        "dalle": _image_job(
            "DALL-E", "dalle_image", "dalle_runner.txt", "D", "dalle",
            {"model": "gpt-image-2", "size": "1536x1024", "quality": "auto"},
            10, 0, temperature=1.0, max_theme=50, max_category=15, retries=3),
        "flux": _image_job(
            "Flux", "flux_story", "flux_runner.txt", "F", "flux",
            {"width": 1344, "height": 768, "steps": 50}, 11, 0),
        "yandex": _image_job(
            "Yandex Art", "yandex_story", "yandex_runner.txt", "Y", "yandex",
            {}, 12, 0, temperature=0.9, retries=3),
        "gemini_image": _image_job(
            "Gemini Image", "gemini_image_story", "gemini_image_runner.txt", "G",
            "gemini_image", {"model": "gemini-2.5-flash-image"}, 13, 0),
        "midjourney_video": _video_job(
            "MidJourney Video", "midjourney_video", ["midjourney_video_image"],
            "midjourney_video_runner.txt", "MV", 14, 0),
        "best_image_video": {
            "title": "Best Image Video", "pipeline": "best_image_video", "media": "video",
            "file_prefix": "best_image_video", "extra_prefixes": ["best_image"],
            "bestof": {"period_days": 7,
                       "video_prompt": "gentle movement, cinematic camera motion",
                       "motion": "high", "task_type": "image-to-video-hd"},
            "watermark": {"enabled": False, "letter": ""},
            "publish": {"chat_id": None, "retries": 0, "debug": False},
            "default_hour": 15, "default_minute": 0,
            "note": "Требует авторизованную Telethon-сессию",
        },
        "zimage": _image_job(
            "Z-Image", "zimage_story", "zimage_runner.txt", "Z", "zimage",
            {"model": "z-image-base-full", "aspect_ratio": "16:9", "num_inference_steps": 30,
             "guidance_scale": 5.0, "use_pe": False}, 16, 0, retries=3),
        "stability_prompts": _image_job(
            "Stability AI (промпт-файл)", "stability_story", "stability_runner.txt",
            "S", "stability",
            {"aspect_ratio": "16:9", "negative_prompt": "low quality, watermark",
             "output_format": "png"}, 17, 0),
        "qwen": _image_job(
            "Qwen Image", "qwen_story", "qwen_runner.txt", "Q", "qwen",
            {"model": "qwen-image-2.1-full", "aspect_ratio": "16:9", "num_inference_steps": 40,
             "guidance_scale": 1.0, "use_pe": False}, 17, 30, retries=3),
        # MiniMax-H3-Image: большие панорамы, 16.8 Мп. Фото в канале Telegram уменьшит
        # до 2560 px, поэтому оригинал уходит следом файлом. Ночью, когда большая
        # карта узла dml свободна от соседей (модели ollama выгружаются).
        "minimax": dict(_image_job(
            "MiniMax H3", "minimax_story", None, "X", "minimax",
            {"aspect_ratio": "16:9"}, 3, 30,
            max_theme=50, max_category=14, retries=3),
            publish={"chat_id": None, "retries": 3, "original_as_document": True}),
        "moss": _image_job(
            "MOSS Image", "moss_story", None, "M", "moss",
            {"aspect_ratio": "16:9", "negative_prompt": "", "num_inference_steps": 50,
             "guidance_scale": 3.0, "use_pe": False}, 8, 0,
            max_theme=50, max_category=14, retries=3),
        "qwen_chat": _image_job(
            "Qwen Chat", "qwen_chat_story", "qwen_chat_runner.txt", "QC", "qwen_chat",
            {"model": "qwen3.7-plus-image", "aspect_ratio": "16:9",
             "temperature": 0.7, "top_p": 0.95}, 18, 0, retries=3),
        "ernie": _image_job(
            "ERNIE", "ernie_story", "ernie_runner.txt", "E", "ernie",
            {"model": "ernie-image-full", "aspect_ratio": "16:9", "num_inference_steps": 100,
             "guidance_scale": 4.0, "use_pe": False}, 18, 30, max_theme=50, retries=3),
        "hidream": _image_job(
            "HiDream", "hidream_story", "hidream_runner.txt", "H", "hidream",
            {"aspect_ratio": "16:9", "num_inference_steps": 50, "guidance_scale": 5.0,
             "shift": 3.0, "scheduler": "default", "use_pe": True},
            19, 0, max_theme=50, retries=3),
    }


def _upgrade_jobs(data: dict) -> bool:
    """Самолечение записей из прежних версий кода (pipeline «legacy» и т.п.)."""
    changed = False
    defaults = _default_jobs()
    for key, job in list(data.items()):
        if job.get("pipeline") == "legacy" and key in defaults:
            fresh = dict(defaults[key])
            fresh["archived"] = job.get("archived", False)
            if job.get("title"):
                fresh["title"] = job["title"]
            data[key] = fresh
            logger.info("Задача «%s» обновлена с legacy на пайплайн «%s»",
                        key, fresh["pipeline"])
            changed = True
    return changed


def load_jobs() -> dict:
    """Читает jobs.json (с кэшем по mtime); при первом обращении создаёт из дефолтов."""
    with _lock:
        try:
            mtime = os.path.getmtime(JOBS_PATH)
            if _cache["mtime"] == mtime and _cache["data"] is not None:
                return _cache["data"]
            with open(JOBS_PATH, encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            data = _default_jobs()
            _write(data)
            mtime = os.path.getmtime(JOBS_PATH)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Не удалось прочитать %s: %s — использую дефолты", JOBS_PATH, exc)
            return _default_jobs()
        if _upgrade_jobs(data):
            _write(data)
            mtime = os.path.getmtime(JOBS_PATH)
        _cache.update(mtime=mtime, data=data)
        return data


def _write(data):
    os.makedirs(os.path.dirname(JOBS_PATH), exist_ok=True)
    tmp_path = JOBS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(tmp_path, JOBS_PATH)
    _cache.update(mtime=os.path.getmtime(JOBS_PATH), data=data)


def get_job(key: str) -> dict:
    job = load_jobs().get(key)
    if job is None:
        raise KeyError(f"Задача «{key}» не найдена в jobs.json")
    return job


def save_job(key: str, job: dict):
    data = load_jobs()
    if key not in data:
        raise KeyError(f"Задача «{key}» не найдена в jobs.json")
    with _lock:
        data[key] = job
        _write(data)

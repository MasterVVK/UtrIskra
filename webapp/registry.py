"""Реестр генераторов панели — строится динамически из core.jobs (jobs.json)."""
from dataclasses import dataclass

from core import jobs as jobs_store


@dataclass(frozen=True)
class Generator:
    key: str
    title: str
    prefixes: tuple        # префиксы имён файлов в storage/images (для галереи)
    media: str             # "image" | "video"
    default_hour: int
    default_minute: int
    note: str
    pipeline: str          # "image" | "midjourney_video" | "best_image_video"
    archived: bool         # в архиве: скрыт с дашборда, расписание отключено
    debug: bool            # публикация этой задачи идёт в отладочный чат


def _to_generator(key, job):
    prefixes = (job["file_prefix"], *job.get("extra_prefixes", []))
    return Generator(
        key=key,
        title=job.get("title", key),
        prefixes=tuple(prefixes),
        media=job.get("media", "image"),
        default_hour=int(job.get("default_hour", 0)),
        default_minute=int(job.get("default_minute", 0)),
        note=job.get("note", ""),
        pipeline=job.get("pipeline", "image"),
        archived=bool(job.get("archived", False)),
        debug=bool(job.get("publish", {}).get("debug", False)),
    )


def get_generators() -> list:
    return [_to_generator(key, job) for key, job in jobs_store.load_jobs().items()]


def get_generator(key: str):
    job = jobs_store.load_jobs().get(key)
    return _to_generator(key, job) if job else None


def generator_for_filename(filename: str):
    """Определяет генератор по префиксу имени файла (самый длинный префикс первым)."""
    pairs = sorted(((prefix, generator)
                    for generator in get_generators()
                    for prefix in generator.prefixes),
                   key=lambda item: len(item[0]), reverse=True)
    for prefix, generator in pairs:
        if filename.startswith(prefix + "_"):
            return generator
    return None

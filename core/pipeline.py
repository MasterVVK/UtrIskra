"""Исполнение задач генерации.

Три типа пайплайна:
- "image"            — промпт из БД → цепочка LLM → image-провайдер → водяной
                        знак → SQLite → публикация;
- "midjourney_video" — промпт → LLM → MJ imagine → публикация кадра →
                        MJ image-to-video → SQLite → публикация видео;
- "best_image_video" — выбор самого популярного фото группы по реакциям
                        (Telethon) → CDN → MJ image-to-video → SQLite →
                        публикация видео.

Выполняется в отдельном потоке со своим event loop (см. webapp/task_manager.py),
поэтому синхронные вызовы (LLM, MidJourney-сервис) допустимы.
"""
import asyncio
import datetime
import logging
import os

from config import IMAGES_PATH
from core import jobs as jobs_store
from core import prompt_batches
from core import prompts as prompts_store
from core import providers_store
from core.publisher import publish_media
from providers.image.base import PromptRejected, build_image_provider, download_bytes
from providers.llm.base import build_llm_provider
from utils.database import save_to_database
from utils.image_utils import add_date_to_image

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TELETHON_SESSION = os.path.join(PROJECT_ROOT, "best_image_session")


def _build_image_path(prefix: str, extension: str = "png") -> str:
    now = datetime.datetime.now()
    directory = os.path.join(IMAGES_PATH, now.strftime("%Y"), now.strftime("%m"))
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}.{extension}")


def _generate_text(job: dict, system_prompt: str, user_prompt: str) -> str:
    """Прогоняет промпт через цепочку LLM-провайдеров; первый успех побеждает."""
    llm_config = job.get("llm", {})
    chain = ([llm_config["provider"]] if llm_config.get("provider")
             else providers_store.llm_chain())
    if not chain:
        raise RuntimeError("Цепочка LLM пуста — проверьте providers.json")
    errors = []
    for name in chain:
        try:
            provider = build_llm_provider(name, providers_store.get_llm_config(name))
            text = provider.generate(system_prompt, user_prompt,
                                     temperature=float(llm_config.get("temperature", 0.7)))
            logger.info("Промпт сгенерирован через LLM «%s» (%d символов)", name, len(text))
            return text.strip()
        except Exception as exc:
            logger.warning("LLM «%s» не сработал: %s", name, exc)
            errors.append(f"{name}: {exc}")
    raise RuntimeError("Все LLM-провайдеры недоступны: " + "; ".join(errors))


def _prepare_prompt(key: str, job: dict):
    """(system, user, generated) — промпт задачи из БД, отрендеренный и прогнанный через LLM.

    Если текст уже заготовлен пакетом (core/prompt_batches.py), берётся он —
    вместе с теми system/user, по которым его писала модель: в историю должно
    попасть именно то, из чего получился текст, а не новый рендер.
    """
    prompt_row = prompts_store.get_prompt(key)
    if prompt_row is None:
        raise RuntimeError(f"У задачи «{key}» нет промпта — задайте его в настройках задачи")
    draft = prompt_batches.take_draft(key, job, prompt_row)
    if draft is not None:
        logger.info("Задача «%s»: промпт взят из пакетной заготовки (пакет %s, %s, "
                    "%d символов) — синхронный вызов LLM не нужен",
                    key, draft["batch_id"], draft.get("model"), len(draft["text"]))
        return draft["system"], draft["user"], draft["text"]
    return _render_and_generate(job, prompt_row)


def _render_and_generate(job: dict, prompt_row: dict):
    """Рендер плейсхолдеров (новые случайные числа) и текст через цепочку LLM."""
    llm_config = job.get("llm", {})
    system_prompt = prompt_row["system"]
    user_prompt = prompts_store.render_user_prompt(
        prompt_row["user"],
        max_theme=int(llm_config.get("max_theme", 10)),
        max_category=int(llm_config.get("max_category", 14)),
    )
    return system_prompt, user_prompt, _generate_text(job, system_prompt, user_prompt)


def _apply_watermark(job: dict, path: str):
    watermark = job.get("watermark", {})
    if watermark.get("enabled", True):
        stamp = f"{watermark.get('letter', '')} {datetime.datetime.now().strftime('%d.%m.%Y')}".strip()
        add_date_to_image(path, stamp)


async def _publish(job: dict, path: str, *, media: str = "image", caption: str = None):
    publish = job.get("publish", {})
    await publish_media(path, media=media,
                        chat_id=publish.get("chat_id"),
                        retries=int(publish.get("retries", 0)),
                        debug=bool(publish.get("debug", False)),
                        caption=caption,
                        original_as_document=bool(publish.get("original_as_document", False)))


def _mj_service():
    from services.midjourney_service import MidjourneyService
    return MidjourneyService()


def _generate_mj_video(service, file_url: str, config: dict) -> str:
    """Создаёт видео из кадра через MidJourney и возвращает URL результата."""
    from services.midjourney_service import extract_output
    video = service.execute_with_retry(
        task_func=lambda: service.create_video_task(
            file_url=file_url,
            prompt=config.get("video_prompt") or config.get("prompt", ""),
            motion=config.get("motion", "high"),
            video_batch_size=1,
            task_type=config.get("task_type", "image-to-video-hd")),
        task_name="image-to-video")
    video_urls = extract_output(video).get("video_urls") or []
    if not video_urls:
        raise RuntimeError(f"MJ не вернул видео: {str(video)[:300]}")
    return video_urls[0]


async def _finish_video(job: dict, video_url: str, *, system_prompt: str,
                        user_prompt: str, generated_prompt: str, caption: str = None):
    """Общий финал видео-пайплайнов: скачать, записать в БД, опубликовать."""
    video_path = _build_image_path(job["file_prefix"], "mp4")
    with open(video_path, "wb") as file:
        file.write(await download_bytes(video_url, timeout=600))
    save_to_database(
        date=datetime.datetime.now().strftime("%Y-%m-%d"),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        generated_prompt=generated_prompt,
        image_path=video_path,
    )
    await _publish(job, video_path, media="video", caption=caption)


# ------------------------------------------------------------------ пайплайны

async def _run_image_job(key: str, job: dict):
    system_prompt, user_prompt, generated_prompt = _prepare_prompt(key, job)

    image_config = job.get("image", {})
    provider_name = image_config["provider"]
    provider = build_image_provider(provider_name,
                                    providers_store.get_image_config(provider_name))
    params = image_config.get("params", {})
    logger.info("Задача «%s»: генерация через «%s» %s", key, provider_name, params)
    # Отказ модерации генератора — не сбой: тот же текст отклонят снова, поэтому
    # пишется новый промпт (с новой темой) и попытка повторяется.
    rewrites = int(job.get("prompt_rewrites_on_reject", 2))
    for attempt in range(rewrites + 1):
        try:
            image_bytes = await provider.generate(generated_prompt, params)
            break
        except PromptRejected as exc:
            if attempt >= rewrites:
                raise
            logger.warning("Задача «%s»: %s — пишу новый промпт (попытка %d из %d). "
                           "Отклонённый текст: %s", key, exc, attempt + 2, rewrites + 1,
                           generated_prompt)
            # Мимо пакетной заготовки: она уже израсходована на отклонённый текст.
            system_prompt, user_prompt, generated_prompt = _render_and_generate(
                job, prompts_store.get_prompt(key))

    extension = str(params.get("output_format", "png")) or "png"
    image_path = _build_image_path(job["file_prefix"], extension)
    with open(image_path, "wb") as file:
        file.write(image_bytes)
    logger.info("Изображение сохранено: %s (%d байт)", image_path, len(image_bytes))

    _apply_watermark(job, image_path)
    save_to_database(
        date=datetime.datetime.now().strftime("%Y-%m-%d"),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        generated_prompt=generated_prompt,
        image_path=image_path,
    )
    await _publish(job, image_path)


async def _run_midjourney_video_job(key: str, job: dict):
    system_prompt, user_prompt, generated_prompt = _prepare_prompt(key, job)
    video_config = job.get("video", {})
    service = _mj_service()

    # Этап 1: изображение
    from services.midjourney_service import extract_output
    imagine = service.execute_with_retry(
        task_func=lambda: service.create_imagine_task(
            generated_prompt, aspect_ratio=video_config.get("aspect_ratio", "16:9")),
        task_name="text-to-image (кадр видео)")
    images = extract_output(imagine).get("images") or []
    if not images or not images[0].get("url"):
        raise RuntimeError(f"MJ не вернул изображения: {str(imagine)[:300]}")
    frame_url = images[0]["url"]

    photo_prefix = (job.get("extra_prefixes") or [job["file_prefix"] + "_image"])[0]
    photo_path = _build_image_path(photo_prefix)
    with open(photo_path, "wb") as file:
        file.write(await download_bytes(frame_url))
    _apply_watermark(job, photo_path)
    await _publish(job, photo_path)
    logger.info("Кадр опубликован, создаю видео…")

    # Этап 2: видео из того же кадра (URL на CDN MidJourney)
    video_url = _generate_mj_video(service, frame_url, video_config)
    await _finish_video(job, video_url, system_prompt=system_prompt,
                        user_prompt=user_prompt, generated_prompt=generated_prompt)


async def _fetch_best_image(period_days: int, download_to: str = None):
    """Самое популярное фото группы за период (реакции через Telethon).

    Сообщения читаются от новых к старым до границы периода — прежний код с
    offset_date, наоборот, отдавал сообщения СТАРШЕ границы.
    Возвращает dict или None; download_to — скачать фото в файл.
    """
    from telethon import TelegramClient
    from telethon.tl.types import MessageMediaPhoto
    from config import TELETHON_API_ID, TELETHON_API_HASH, TELETHON_PEER

    if not (TELETHON_API_ID and TELETHON_API_HASH and TELETHON_PEER):
        raise RuntimeError("TELETHON_API_ID / TELETHON_API_HASH / TELETHON_PEER не заданы в .env")

    client = TelegramClient(TELETHON_SESSION, TELETHON_API_ID, TELETHON_API_HASH)
    # client.start() при неавторизованной сессии интерактивно спрашивает телефон —
    # в сервисе это недопустимо, поэтому проверяем авторизацию явно
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(
            f"Telethon-сессия не авторизована ({TELETHON_SESSION}.session). "
            "Выполните на сервере разово: .venv/bin/python -m core.telethon_login")
    try:
        peer = int(TELETHON_PEER) if TELETHON_PEER.lstrip("-").isdigit() else TELETHON_PEER
        entity = await client.get_entity(peer)
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=period_days)
        best = None
        checked = 0
        # сообщения идут от новых к старым — граница периода останавливает перебор
        async for message in client.iter_messages(entity):
            if message.date < since:
                break
            if message.media and isinstance(message.media, MessageMediaPhoto):
                checked += 1
                reactions = sum(r.count for r in message.reactions.results) \
                    if message.reactions else 0
                if best is None or reactions > best["reactions"]:
                    best = {"message_id": message.id, "date": message.date,
                            "reactions": reactions}
        logger.info("Best-of: просмотрено фото за %d дн.: %d, лучшее: %s",
                    period_days, checked, best)
        if not best or best["reactions"] == 0:
            return None
        if download_to:
            message = await client.get_messages(entity, ids=best["message_id"])
            await client.download_media(message, file=download_to)
        return best
    finally:
        await client.disconnect()


async def _run_best_image_video_job(key: str, job: dict):
    config = job.get("bestof", {})
    period_days = int(config.get("period_days", 7))

    photo_prefix = (job.get("extra_prefixes") or ["best_image"])[0]
    photo_path = _build_image_path(photo_prefix, "jpg")  # фото Telegram — всегда JPEG
    best = await _fetch_best_image(period_days, download_to=photo_path)
    if best is None:
        logger.info("Задача «%s»: за %d дн. нет фото с реакциями — пропуск", key, period_days)
        return

    # На CDN Kolersky (вместо стороннего catbox.moe), оттуда — в видео
    service = _mj_service()
    cdn_url = service.upload_image(photo_path)

    caption = (f"🎬 Оживление популярного изображения\n"
               f"📊 Реакций: {best['reactions']} · опубликовано "
               f"{best['date'].strftime('%d.%m.%Y %H:%M')}")
    await _publish(job, photo_path, caption=caption)

    video_url = _generate_mj_video(service, cdn_url, config)
    await _finish_video(job, video_url, system_prompt="",
                        user_prompt=f"best-of по реакциям за {period_days} дн.",
                        generated_prompt=caption)


PIPELINES = {
    "image": _run_image_job,
    "midjourney_video": _run_midjourney_video_job,
    "best_image_video": _run_best_image_video_job,
}


async def run_job(key: str):
    job = jobs_store.get_job(key)
    pipeline = job.get("pipeline", "image")
    runner = PIPELINES.get(pipeline)
    if runner is None:
        raise RuntimeError(f"Неизвестный пайплайн «{pipeline}» у задачи «{key}»")
    await runner(key, job)
    logger.info("Задача «%s» завершена успешно", key)


def run_job_sync(key: str):
    """Запуск в отдельном потоке/из CLI — свой event loop."""
    asyncio.run(run_job(key))

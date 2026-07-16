"""Исполнение задач генерации.

Пайплайн «image»: промпт-файл → цепочка LLM → image-провайдер → водяной знак
→ SQLite → публикация в Telegram. Задачи с pipeline="legacy" запускают
функцию старого раннера без изменений.

Выполняется в отдельном потоке со своим event loop (см. webapp/task_manager.py),
поэтому синхронные вызовы LLM-провайдеров допустимы.
"""
import asyncio
import datetime
import importlib
import logging
import os

from config import IMAGES_PATH
from core import jobs as jobs_store
from core import prompts as prompts_store
from core import providers_store
from core.publisher import publish_media
from providers.image.base import build_image_provider
from providers.llm.base import build_llm_provider
from utils.database import save_to_database
from utils.image_utils import add_date_to_image

logger = logging.getLogger(__name__)


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


async def run_job(key: str):
    job = jobs_store.get_job(key)

    if job.get("pipeline") == "legacy":
        logger.info("Задача «%s»: legacy-раннер %s.%s", key, job["module"], job["func"])
        module = importlib.import_module(job["module"])
        await getattr(module, job["func"])()
        return

    # 1. Промпт из БД + LLM
    llm_config = job.get("llm", {})
    prompt_row = prompts_store.get_prompt(key)
    if prompt_row is None:
        raise RuntimeError(f"У задачи «{key}» нет промпта — задайте его в настройках задачи")
    system_prompt = prompt_row["system"]
    user_prompt = prompts_store.render_user_prompt(
        prompt_row["user"],
        max_theme=int(llm_config.get("max_theme", 10)),
        max_category=int(llm_config.get("max_category", 14)),
    )
    generated_prompt = _generate_text(job, system_prompt, user_prompt)

    # 2. Генерация изображения
    image_config = job.get("image", {})
    provider_name = image_config["provider"]
    provider = build_image_provider(provider_name,
                                    providers_store.get_image_config(provider_name))
    params = image_config.get("params", {})
    logger.info("Задача «%s»: генерация через «%s» %s", key, provider_name, params)
    image_bytes = await provider.generate(generated_prompt, params)

    # 3. Сохранение + водяной знак
    extension = str(params.get("output_format", "png")) or "png"
    image_path = _build_image_path(job["file_prefix"], extension)
    with open(image_path, "wb") as file:
        file.write(image_bytes)
    logger.info("Изображение сохранено: %s (%d байт)", image_path, len(image_bytes))

    watermark = job.get("watermark", {})
    if watermark.get("enabled", True):
        stamp = f"{watermark.get('letter', '')} {datetime.datetime.now().strftime('%d.%m.%Y')}".strip()
        add_date_to_image(image_path, stamp)

    # 4. Учёт
    save_to_database(
        date=datetime.datetime.now().strftime("%Y-%m-%d"),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        generated_prompt=generated_prompt,
        image_path=image_path,
    )

    # 5. Публикация
    publish = job.get("publish", {})
    await publish_media(image_path, media=job.get("media", "image"),
                        chat_id=publish.get("chat_id"),
                        retries=int(publish.get("retries", 0)),
                        debug=bool(publish.get("debug", False)))
    logger.info("Задача «%s» завершена успешно", key)


def run_job_sync(key: str):
    """Запуск в отдельном потоке/из CLI — свой event loop."""
    asyncio.run(run_job(key))

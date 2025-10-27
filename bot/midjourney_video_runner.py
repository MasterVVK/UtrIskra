import os
import asyncio
import datetime
import sys

# Добавляем корневую директорию в путь для импорта
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, PROMPTS_DIR
from services.midjourney_service import MidjourneyService
from services.gemini_service import GeminiService
from utils.database import initialize_database, save_to_database
from utils.image_utils import create_video_path, download_video
from utils.prompt_utils import generate_dynamic_prompt
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPTS_FILE = os.path.join(PROMPTS_DIR, "midjourney_video_runner.txt")

async def send_midjourney_video_story():
    """
    Генерация и отправка динамичного видео через Midjourney API.
    """
    bot = Bot(token=TELEGRAM_TOKEN)
    midjourney_service = MidjourneyService()
    gemini_service = GeminiService()

    try:
        # Читаем промпты из файла
        system_prompt, user_prompt = generate_dynamic_prompt(PROMPTS_FILE)

        logger.info(f"Генерация текста через Gemini с промптом: {user_prompt}")
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=1
        )

        # Удаляем дополнительные символы из промпта
        if '---' in generated_prompt:
            generated_prompt = generated_prompt.split('---')[0].strip()
        else:
            generated_prompt = generated_prompt.strip()
        logger.info(f"Сгенерированный промпт для Midjourney: {generated_prompt}")

        # Шаг 1: Генерация изображения через Midjourney
        logger.info("Генерация изображения через Midjourney...")
        imagine_task = midjourney_service.create_imagine_task(generated_prompt, aspect_ratio="16:9")

        if "requestId" not in imagine_task:
            logger.error(f"Ключ 'requestId' отсутствует в ответе: {imagine_task}")
            raise KeyError("Ключ 'requestId' отсутствует в ответе.")

        request_id_image = imagine_task["requestId"]
        logger.info(f"Ожидание завершения задачи генерации изображения {request_id_image}...")
        imagine_result = midjourney_service.wait_for_task_completion(request_id_image)

        # Получаем URL первого изображения из массива images
        images = imagine_result.get("data", {}).get("output", {}).get("images", [])
        if not images:
            raise ValueError(f"Не удалось получить изображения. Структура ответа: {imagine_result}")

        # Берем первое изображение
        first_image_url = images[0].get("url")
        if not first_image_url:
            raise ValueError(f"Не удалось получить URL первого изображения. Структура ответа: {imagine_result}")

        logger.info(f"Получен URL изображения: {first_image_url}")

        # Шаг 2: Создание видео из изображения
        logger.info("Создание видео из изображения...")
        video_task = midjourney_service.create_video_task(
            file_url=first_image_url,
            prompt="gentle movement, cinematic camera motion",
            motion="high",
            video_batch_size=1,
            task_type="image-to-video"
        )

        if "requestId" not in video_task:
            logger.error(f"Ключ 'requestId' отсутствует в ответе видео: {video_task}")
            raise KeyError("Ключ 'requestId' отсутствует в ответе видео.")

        request_id_video = video_task["requestId"]
        logger.info(f"Ожидание завершения задачи генерации видео {request_id_video}...")
        video_result = midjourney_service.wait_for_task_completion(request_id_video)

        # Получаем URL видео
        video_urls = video_result.get("data", {}).get("output", {}).get("video_urls", [])
        if not video_urls:
            raise ValueError(f"Не удалось получить URL видео. Структура ответа: {video_result}")

        video_url = video_urls[0]
        logger.info(f"Получен URL видео: {video_url}")

        # Скачивание видео
        video_path = create_video_path(prefix="midjourney_video")
        logger.info("Скачивание видео...")
        download_video(video_url, video_path)

        # Сохранение в базу данных
        save_to_database(
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            generated_prompt=generated_prompt,
            image_path=video_path  # Используем поле image_path для хранения пути к видео
        )

        # Отправка видео в Telegram
        logger.info("Отправка видео в Telegram...")
        await bot.send_video(chat_id=TARGET_CHAT_ID, video=FSInputFile(video_path))
        logger.info("Видео успешно отправлено!")

    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    initialize_database()
    asyncio.run(send_midjourney_video_story())

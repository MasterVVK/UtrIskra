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
from utils.image_utils import create_video_path, download_video, create_image_path, download_image, add_date_to_image
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

        # Шаг 1: Генерация изображения через Midjourney с повторными попытками
        logger.info("Генерация изображения через Midjourney...")
        imagine_result = midjourney_service.execute_with_retry(
            task_func=lambda: midjourney_service.create_imagine_task(generated_prompt, aspect_ratio="16:9"),
            task_name="text-to-image для видео",
            max_retries=2,
            retry_delay=300  # 5 минут
        )

        # Получаем URL первого изображения из массива images
        images = imagine_result.get("data", {}).get("output", {}).get("images", [])
        if not images:
            raise ValueError(f"Не удалось получить изображения. Структура ответа: {imagine_result}")

        # Берем первое изображение
        first_image_url = images[0].get("url")
        if not first_image_url:
            raise ValueError(f"Не удалось получить URL первого изображения. Структура ответа: {imagine_result}")

        logger.info(f"Получен URL изображения: {first_image_url}")

        # Скачиваем и сохраняем исходное изображение
        image_path = create_image_path(prefix="midjourney_video_image")
        logger.info("Скачивание исходного изображения...")
        download_image(first_image_url, image_path)

        # Добавляем дату на изображение
        current_date_text = "MV " + datetime.datetime.now().strftime("%d.%m.%Y")
        add_date_to_image(image_path, current_date_text)

        # Отправляем изображение в Telegram
        logger.info("Отправка исходного изображения в Telegram...")
        await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=FSInputFile(image_path))
        logger.info("Исходное изображение успешно отправлено!")

        # Шаг 2: Создание видео из изображения с повторными попытками
        logger.info("Создание видео из изображения...")
        video_result = midjourney_service.execute_with_retry(
            task_func=lambda: midjourney_service.create_video_task(
                file_url=first_image_url,
                prompt="gentle movement, cinematic camera motion",
                motion="high",
                video_batch_size=1,
                task_type="image-to-video-hd"  # HD качество
            ),
            task_name="image-to-video-hd",
            max_retries=2,
            retry_delay=300  # 5 минут
        )

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

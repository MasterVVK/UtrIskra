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
from utils.image_utils import add_date_to_image, create_image_path, download_image, crop_image
from utils.prompt_utils import generate_dynamic_prompt
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPTS_FILE = os.path.join(PROMPTS_DIR, "midjourney_runner.txt")  # Путь к файлу с промптами

async def send_midjourney_story():
    """
    Генерация и отправка вдохновляющего изображения через Midjourney API.
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

        # Генерация изображения через Midjourney с повторными попытками
        logger.info("Генерация изображения через Midjourney...")
        imagine_result = midjourney_service.execute_with_retry(
            task_func=lambda: midjourney_service.create_imagine_task(generated_prompt, aspect_ratio="16:9"),
            task_name="text-to-image",
            max_retries=2,
            retry_delay=300  # 5 минут
        )

        # Проверка URL изображения (структура: data.output.collage.image_url)
        grid_image_url = imagine_result.get("data", {}).get("output", {}).get("collage", {}).get("image_url")
        if not grid_image_url:
            raise ValueError(f"Не удалось получить URL сетки изображений. Структура ответа: {imagine_result}")

        # Скачивание необработанного изображения
        raw_image_path = create_image_path(prefix="midjourney_story")
        logger.info("Сохранение необработанного изображения...")
        download_image(grid_image_url, raw_image_path)

        # Вырезание первого изображения
        processed_image_path = raw_image_path.replace(".png", "_processed.png")
        crop_image(raw_image_path, processed_image_path, position=1)

        # Добавление даты на обработанное изображение
        current_date_text = "M " + datetime.datetime.now().strftime("%d.%m.%Y")
        add_date_to_image(processed_image_path, current_date_text)

        # Сохранение в базу данных
        save_to_database(
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            generated_prompt=generated_prompt,
            image_path=processed_image_path
        )

        # Отправка изображения в Telegram
        logger.info("Отправка изображения в Telegram...")
        await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=FSInputFile(processed_image_path))
        logger.info("Изображение успешно отправлено!")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    initialize_database()
    asyncio.run(send_midjourney_story())

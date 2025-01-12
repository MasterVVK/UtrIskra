import os
import asyncio
import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, PROMPTS_DIR
from services.dalle_service import DalleService
from services.gemini_service import GeminiService
from utils.database import initialize_database, save_to_database
from utils.image_utils import add_date_to_image, create_image_path, download_image
from utils.prompt_utils import generate_dynamic_prompt
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPTS_FILE = os.path.join(PROMPTS_DIR, "dalle_runner.txt")  # Формируем путь к файлу промптов

async def send_dalle_story():
    """
    Генерация и отправка изображения через DALL·E API.
    """
    bot = Bot(token=TELEGRAM_TOKEN)
    dalle_service = DalleService()
    gemini_service = GeminiService()

    try:
        # Читаем промпты из файла
        system_prompt, user_prompt = generate_dynamic_prompt(PROMPTS_FILE)

        logger.info(f"Генерация текста через Gemini с промптом: {user_prompt}")
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=1.0
        )

        logger.info(f"Сгенерированный промпт для DALL·E: {generated_prompt}")

        # Генерация изображения через DALL·E
        image_url = dalle_service.generate_image(
            prompt=generated_prompt,
            model="dall-e-3",
            size="1024x1792",
            quality="hd",
            n=1
        )

        # Скачивание изображения
        raw_image_path = create_image_path(prefix="dalle_image")
        logger.info("Сохранение изображения...")
        download_image(image_url, raw_image_path)

        # Добавление даты на изображение
        current_date_text = "D " + datetime.datetime.now().strftime("%d.%m.%Y")
        add_date_to_image(raw_image_path, current_date_text)

        # Сохранение в базу данных
        save_to_database(
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            generated_prompt=generated_prompt,
            image_path=raw_image_path
        )

        # Отправка изображения в Telegram
        logger.info("Отправка изображения в Telegram...")
        await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=FSInputFile(raw_image_path))
        logger.info("Изображение успешно отправлено!")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    initialize_database()
    asyncio.run(send_dalle_story())

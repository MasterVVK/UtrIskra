import os
import asyncio
import datetime
import sys

# Добавляем корневую директорию в путь для импорта
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from aiogram import Bot
from aiogram.types import FSInputFile
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientTimeout
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, PROMPTS_DIR
from services.qwen_service import QwenService
from services.gemini_service import GeminiService
from utils.database import initialize_database, save_to_database
from utils.image_utils import add_date_to_image, create_image_path, download_image
from utils.prompt_utils import generate_dynamic_prompt
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPTS_FILE = os.path.join(PROMPTS_DIR, "qwen_runner.txt")


async def send_qwen_story():
    """
    Генерация и отправка изображения через Qwen-Image API.
    """
    session = AiohttpSession(timeout=ClientTimeout(total=300, sock_connect=30, sock_read=300))
    bot = Bot(token=TELEGRAM_TOKEN, session=session)
    qwen_service = QwenService()
    gemini_service = GeminiService()

    try:
        # Читаем промпты из файла
        system_prompt, user_prompt = generate_dynamic_prompt(PROMPTS_FILE)

        logger.info(f"Генерация текста через Gemini Pro: {user_prompt}")
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7
        )

        logger.info(f"Сгенерированный промпт для Qwen: {generated_prompt}")

        # Генерация изображения через Qwen API
        logger.info("Генерация изображения через Qwen...")
        image_url = await qwen_service.generate_image(
            prompt=generated_prompt,
            aspect_ratio="16:9",
        )

        # Сохранение изображения
        image_path = create_image_path(prefix="qwen_story")
        download_image(image_url, image_path)

        current_date_text = "Q " + datetime.datetime.now().strftime("%d.%m.%Y")
        add_date_to_image(image_path, current_date_text)

        # Сохранение в базу данных
        save_to_database(
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            generated_prompt=generated_prompt,
            image_path=image_path
        )

        # Отправка изображения в Telegram с retry
        logger.info("Отправка изображения в Telegram...")
        for attempt in range(3):
            try:
                await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=FSInputFile(image_path))
                logger.info("Изображение успешно отправлено!")
                break
            except Exception as e:
                if attempt < 2:
                    logger.warning(f"Попытка {attempt + 1}/3 не удалась: {e}. Повтор через 10 сек...")
                    await asyncio.sleep(10)
                else:
                    raise
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    initialize_database()
    asyncio.run(send_qwen_story())

import os
import asyncio
import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, PROMPTS_DIR
from services.flux_service import FluxService
from services.gemini_service import GeminiService  # Вернул импорт GeminiService
from utils.database import initialize_database, save_to_database
from utils.image_utils import add_date_to_image, create_image_path, download_image
from utils.prompt_utils import generate_dynamic_prompt
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPTS_FILE = os.path.join(PROMPTS_DIR, "flux_runner.txt")  # Формируем путь к файлу промптов


async def send_flux_story():
    """
    Генерация и отправка изображения через Flux API.
    """
    bot = Bot(token=TELEGRAM_TOKEN)
    flux_service = FluxService()
    gemini_service = GeminiService()  # Создаем экземпляр GeminiService

    try:
        # Читаем промпты из файла
        system_prompt, user_prompt = generate_dynamic_prompt(PROMPTS_FILE)

        logger.info(f"Генерация текста через Gemini Pro: {user_prompt}")
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7
        )

        logger.info(f"Сгенерированный промпт для Flux: {generated_prompt}")

        # Генерация изображения через Flux API
        logger.info("Генерация изображения через Flux...")
        request_id = await flux_service.create_request(generated_prompt)
        image_url = await flux_service.poll_for_result(request_id)

        # Сохранение изображения
        image_path = create_image_path(prefix="flux_story")
        download_image(image_url, image_path)

        current_date_text = "F " + datetime.datetime.now().strftime("%d.%m.%Y")
        add_date_to_image(image_path, current_date_text)

        # Сохранение в базу данных
        save_to_database(
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            generated_prompt=generated_prompt,
            image_path=image_path
        )

        # Отправка изображения в Telegram
        logger.info("Отправка изображения в Telegram...")
        await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=FSInputFile(image_path))
        logger.info("Изображение успешно отправлено!")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    initialize_database()
    asyncio.run(send_flux_story())

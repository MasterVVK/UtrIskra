import os
import asyncio
import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, PROMPTS_DIR
from services.stability_service import StabilityService
from services.gemini_service import GeminiService
from utils.database import initialize_database, save_to_database
from utils.image_utils import add_date_to_image, create_image_path
from utils.prompt_utils import generate_dynamic_prompt
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPTS_FILE = os.path.join(PROMPTS_DIR, "stability_runner.txt")  # Формируем путь к файлу промптов


async def send_daily_story():
    """
    Генерация и отправка изображения через Stability API в Telegram-группу.
    """
    bot = Bot(token=TELEGRAM_TOKEN)
    gemini_service = GeminiService()
    stability_service = StabilityService()

    try:
        # Читаем промпты из файла
        system_prompt, user_prompt = generate_dynamic_prompt(PROMPTS_FILE)

        logger.info(f"Генерация текста через Gemini Pro: {user_prompt}")
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7
        )

        logger.info(f"Сгенерированный промпт для Stability: {generated_prompt}")

        # Генерация изображения через Stability API
        logger.info("Генерация изображения через Stability AI...")
        image_path = create_image_path(prefix="stability_story")
        image_content = await stability_service.generate_image(generated_prompt)
        with open(image_path, "wb") as file:
            file.write(image_content)

        logger.info(f"Изображение сохранено в {image_path}")

        # Добавление даты на изображение
        current_date_text = "S " + datetime.datetime.now().strftime("%d.%m.%Y")
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
    asyncio.run(send_daily_story())

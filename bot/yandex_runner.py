import asyncio
import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID
from services.gemini_service import GeminiService
from services.yandex_service import YandexArtService
from utils.database import initialize_database, save_to_database
from utils.image_utils import add_date_to_image, save_image_from_base64, create_image_path
from utils.prompt_utils import generate_dynamic_prompt
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPTS_FILE = "prompts/yandex_runner.txt"  # Путь к файлу с промптами

async def send_daily_story():
    """Генерация и отправка вдохновляющей картинки в Telegram-группу."""
    bot = Bot(token=TELEGRAM_TOKEN)
    gemini_service = GeminiService()
    yandex_art_service = YandexArtService()

    try:
        # Читаем промпты из файла
        system_prompt, user_prompt = generate_dynamic_prompt(PROMPTS_FILE)

        logger.info(f"Генерация текста через Gemini Pro: {user_prompt}")
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.9
        )

        logger.info(f"Сгенерированный промпт: {generated_prompt}")

        # Генерация изображения через Yandex-Art
        logger.info("Генерация изображения через Yandex-Art...")
        base64_image = yandex_art_service.generate_image(generated_prompt)

        # Сохранение изображения
        image_path = create_image_path(prefix="yandex_story")
        save_image_from_base64(base64_image, image_path)

        current_date_text = "Y " + datetime.datetime.now().strftime("%d.%m.%Y")
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
        logger.info("Отправка изображения в Telegram-группу...")
        await bot.send_photo(
            chat_id=TARGET_CHAT_ID,
            photo=FSInputFile(image_path)
        )
        logger.info("Изображение успешно отправлено!")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    initialize_database()
    asyncio.run(send_daily_story())

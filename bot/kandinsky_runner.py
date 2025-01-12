import os
import asyncio
import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, PROMPTS_DIR
from services.gemini_service import GeminiService
from services.kandinsky_service import KandinskyService
from utils.database import initialize_database, save_to_database
from utils.image_utils import add_date_to_image, save_image_from_base64, create_image_path
from utils.prompt_utils import generate_dynamic_prompt
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPTS_FILE = os.path.join(PROMPTS_DIR, "kandinsky_runner.txt")  # Путь к файлу с промптами

async def send_kandinsky_story():
    """Генерация и отправка изображения через Kandinsky API."""
    bot = Bot(token=TELEGRAM_TOKEN)
    gemini_service = GeminiService()
    kandinsky_service = KandinskyService()

    try:
        # Читаем промпты из файла
        system_prompt, user_prompt = generate_dynamic_prompt(PROMPTS_FILE)

        logger.info(f"Генерация текста через Gemini Pro: {user_prompt}")
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=1.0
        )

        # Проверяем длину промпта
        if len(generated_prompt) > 1000:
            logger.warning("Промпт превышает допустимый лимит в 1000 символов. Обрезаем текст.")
            generated_prompt = generated_prompt[:1000]

        logger.info(f"Сгенерированный промпт: {generated_prompt}")

        # Работа с Kandinsky API
        logger.info("Получаем ID модели Kandinsky...")
        model_id = kandinsky_service.get_model_id()
        kandinsky_service.check_availability_with_timeout(model_id)

        logger.info("Генерация изображения через Kandinsky...")
        uuid = kandinsky_service.generate_image(generated_prompt, model_id)

        logger.info("Ожидание результата генерации...")
        base64_image = kandinsky_service.get_image(uuid, attempts=120, delay=10)

        # Сохранение изображения
        image_path = create_image_path(prefix="kandinsky_story")
        save_image_from_base64(base64_image, image_path)

        current_date_text = "K " + datetime.datetime.now().strftime("%d.%m.%Y")
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
    asyncio.run(send_kandinsky_story())

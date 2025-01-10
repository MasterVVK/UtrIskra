import asyncio
import os
import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID
from services.gemini_service import GeminiService
from services.kandinsky_service import KandinskyService
import logging
from utils.database import initialize_database, save_to_database
from utils.image_utils import save_image_from_base64, add_date_to_image, create_image_path

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def send_kandinsky_story():
    """Генерация и отправка изображения через Kandinsky API."""
    bot = Bot(token=TELEGRAM_TOKEN)
    gemini_service = GeminiService()
    kandinsky_service = KandinskyService()

    try:
        logger.info("Получаем ID модели...")
        model_id = kandinsky_service.get_model_id()
        logger.info(f"Проверяем доступность сервиса Kandinsky для model_id={model_id}...")
        kandinsky_service.check_availability_with_timeout(model_id)

        current_date = datetime.datetime.now().strftime("%d %B %Y")
        user_prompt = (
            f"Today is {current_date}.\n"
            "Сгенерируй 10 различных вдохновляющих тем для создания иллюстраций, со своей техникой рисования."
            "Для каждой темы укажи конкретную точку зрения, старайся не повторяться. "
            "Краткое описание (3–6 предложения и действия) "
            "Расширенные стилистические ориентиры (жанр, эстетика, детали оформления, цветовая палитра, техникой рисования и т.п.) "
            "Если в теме вдруг встречаются флаги, они должны быть полностью выдуманными (не связанными с реальными странами). "
            "Включить хотя бы один интересный элемент, чтобы сделать изображение более интригующим. "

            "Используй номер дня месяца (например, 1…31) и рассчитай индекс как (день % 10)."
            "Если результат равен 0, выбирай 10-ю тему; "
            "Если результат не равен 0, выбирай тему с номером, равным результату."
            "Выведи только выбранную тему. Не нужно выводить список тем и результат расчета. "
            "Выводи для выбранной темы только текст. "
            "Ответ должен содержать только текст из 950 символов"
        )
        logger.info(f"Генерация текста через Gemini: {user_prompt}")

        system_prompt = "Ответ должен содержать только текст из 950 символов"
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=1.0
        )

        if len(generated_prompt) > 1000:
            logger.warning("Промпт превышает допустимый лимит в 1000 символов. Обрезаем текст.")
            generated_prompt = generated_prompt[:1000]

        logger.info(f"Сгенерированный промпт: {generated_prompt}")
        uuid = kandinsky_service.generate_image(generated_prompt, model_id)

        logger.info("Ожидание результата генерации...")
        base64_image = kandinsky_service.get_image(uuid, attempts=120, delay=10)

        # Создаем путь для изображения
        image_path = create_image_path(prefix="kandinsky_story")

        save_image_from_base64(base64_image, image_path)
        add_date_to_image(image_path, "K " + datetime.datetime.now().strftime("%d.%m.%Y"))

        save_to_database(
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            generated_prompt=generated_prompt,
            image_path=image_path
        )

        await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=FSInputFile(image_path))
        logger.info("Изображение успешно отправлено!")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        # Закрываем сессию бота
        await bot.session.close()

if __name__ == "__main__":
    initialize_database()
    asyncio.run(send_kandinsky_story())

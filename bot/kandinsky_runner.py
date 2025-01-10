import asyncio
import base64
import os
import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, IMAGES_PATH, FONTS_PATH
from services.gemini_service import GeminiService
from services.kandinsky_service import KandinskyService
from PIL import Image, ImageDraw, ImageFont
import logging
from utils.database import initialize_database, save_to_database

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def save_image_from_base64(base64_image: str, file_path: str):
    """Сохраняет изображение из Base64 в файл."""
    with open(file_path, "wb") as file:
        file.write(base64.b64decode(base64_image))

def add_date_to_image(image_path: str, date_text: str):
    """Добавляет дату на изображение."""
    try:
        font_path = f"{FONTS_PATH}/Roboto-Regular.ttf"
        if not os.path.exists(font_path):
            raise FileNotFoundError(f"Шрифт '{font_path}' не найден.")

        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)
        font_size = int(min(img.size) * 0.05)
        font = ImageFont.truetype(font_path, font_size)

        text_position = (img.size[0] - font_size * len(date_text) - 10, img.size[1] - font_size - 10)
        text_color = (255, 255, 255)
        shadow_color = (0, 0, 0)
        shadow_offset = 2

        draw.text(
            (text_position[0] + shadow_offset, text_position[1] + shadow_offset),
            date_text,
            font=font,
            fill=shadow_color,
        )
        draw.text(text_position, date_text, font=font, fill=text_color)
        img.save(image_path)
    except Exception as e:
        logger.error(f"Ошибка при добавлении даты на изображение: {e}")

async def send_kandinsky_story():
    """Генерация и отправка изображения через Kandinsky API."""
    bot = Bot(token=TELEGRAM_TOKEN)
    gemini_service = GeminiService()
    kandinsky_service = KandinskyService()

    try:
        user_prompt = "Create a surreal landscape with futuristic elements."
        logger.info(f"Генерация текста через Gemini: {user_prompt}")

        system_prompt = "Generate an inspiring art description."
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=1.0
        )

        if len(generated_prompt) > 1000:
            logger.warning("Промпт превышает допустимый лимит в 1000 символов. Обрезаем текст.")
            generated_prompt = generated_prompt[:1000]

        logger.info(f"Сгенерированный промпт: {generated_prompt}")
        model_id = kandinsky_service.get_model_id()
        uuid = kandinsky_service.generate_image(generated_prompt, model_id)

        logger.info(f"Ожидание результата генерации...")
        # Увеличиваем ожидание до 20 минут
        base64_image = kandinsky_service.get_image(uuid, attempts=120, delay=10)

        image_path = os.path.join(IMAGES_PATH, "kandinsky_story.png")
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



if __name__ == "__main__":
    initialize_database()
    asyncio.run(send_kandinsky_story())

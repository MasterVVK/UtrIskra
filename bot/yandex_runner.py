import asyncio
import datetime
import os
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, IMAGES_PATH, FONTS_PATH
from services.gemini_service import GeminiService
from services.yandex_service import YandexArtService
from PIL import Image, ImageDraw, ImageFont
import logging
from utils.database import initialize_database, save_to_database

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_date_to_image(image_path: str, date_text: str):
    """
    Добавляет дату на изображение.
    """
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
        logger.info(f"Дата '{date_text}' добавлена на изображение {image_path}")
    except Exception as e:
        logger.error(f"Ошибка при добавлении даты на изображение: {e}")

def generate_dynamic_prompt():
    """
    Генерирует универсальный промпт для Gemini Pro с использованием даты и заданной тематики.
    """
    current_date = datetime.datetime.now().strftime("%d %B %Y")
    return (
        f"Today is {current_date}.\n"
        "Create a beautiful artistic image using Yandex-Art. Themes can include nature, harmony, and creativity."
    )

async def send_daily_story():
    """
    Генерация и отправка вдохновляющей картинки в Telegram-группу.
    """
    bot = Bot(token=TELEGRAM_TOKEN)
    gemini_service = GeminiService()
    yandex_art_service = YandexArtService()

    try:
        user_prompt = generate_dynamic_prompt()
        logger.info(f"Генерация текста через Gemini Pro: {user_prompt}")
        current_date = datetime.datetime.now().strftime("%d %B %Y")
        system_prompt = (
#            "Create a beautiful and inspiring text prompt for an artistic image. Text only"
            f"Today is {current_date}.\n"
            "Сгенерировать одну случайную тему на основе текущей даты. "
            "Сгенерируй 10 различных вдохновляющих тем для создания иллюстраций."
            "Используй номер дня месяца (например, 1…31) и рассчитай индекс как (день % 10)."
            "Если результат равен 0, выбирай 10-ю тему; "
            "Если результат не равен 0, выбирай тему с номером, равным результату."
            f"Выведи только одну выбранную тему. В ней должны быть:\n"
            "Короткий заголовок "
            "Краткое описание (2–4 предложения) "
            "Расширенные стилистические ориентиры (жанр, эстетика, детали оформления, цветовая палитра и т.п.) "
            "Если в теме вдруг встречаются флаги, они должны быть полностью выдуманными (не связанными с реальными странами). "
            "Включить хотя бы один неожиданный или сюрреалистический элемент, чтобы сделать изображение более интригующим. "
            "Ландшафтные композиции"
            "Ответ должен содержать только текст из 500 символов"
        )
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=1.0
        )
        logger.info(f"Сгенерированный промпт: {generated_prompt}")

        logger.info("Генерация изображения через Yandex-Art...")
        image_path = yandex_art_service.generate_image(generated_prompt)
        logger.info(f"Изображение сохранено в {image_path}")

        current_date_text = "Y " + datetime.datetime.now().strftime("%d.%m.%Y")
        add_date_to_image(image_path, current_date_text)

        save_to_database(
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            generated_prompt=generated_prompt,
            image_path=image_path
        )

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

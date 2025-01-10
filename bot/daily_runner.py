import asyncio
import datetime
import os
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, IMAGES_PATH, FONTS_PATH
from services.gemini_service import GeminiService
from services.stability_service import StabilityService
from PIL import Image, ImageDraw, ImageFont
import logging
from utils.database import initialize_database, save_to_database

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_image_path():
    """
    Создает путь для сохранения изображения в формате: storage/images/{year}/{month}/{file_name}.
    """
    current_date = datetime.datetime.now()
    year = current_date.strftime("%Y")
    month = current_date.strftime("%m")
    file_name = f"daily_story_{current_date.strftime('%Y%m%d_%H%M%S')}.png"

    directory = os.path.join(IMAGES_PATH, year, month)
    os.makedirs(directory, exist_ok=True)

    return os.path.join(directory, file_name)

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
        "Сгенерируй 10 различных жизнеутверждающих и вдохновляющих тем для создания иллюстраций, со своей техникой рисования."
        "Для каждой темы укажи конкретную точку зрения, старайся не повторяться. "
        "Краткое описание (3–6 предложения и действия) "
        "Расширенные стилистические ориентиры (жанр, эстетика, детали оформления, цветовая палитра, техникой рисования и т.п.) "
        "Если в теме вдруг встречаются флаги, они должны быть полностью выдуманными (не связанными с реальными странами). "
        "Включить хотя бы один интересный элемент, чтобы сделать изображение более интригующим. "
        
        "Используй номер дня месяца (например, 1…31) и рассчитай индекс как (день % 10)."
        "Если результат равен 0, выбирай 10-ю тему; "
        "Если результат не равен 0, выбирай тему с номером, равным результату."
        f"Выведи только выбранную тему. Не нужно выводит список тем и результат расчета. "
        "Выводи для выбранной темы только текст. "
        "Use text only and write in English. "
    )

async def send_daily_story():
    """
    Генерация и отправка вдохновляющей картинки в Telegram-группу.
    """
    bot = Bot(token=TELEGRAM_TOKEN)
    gemini_service = GeminiService()
    stability_service = StabilityService()

    try:
        user_prompt = generate_dynamic_prompt()
        logger.info(f"Генерация текста через Gemini Pro на тему: {user_prompt}")
        system_prompt = (
#            "Create a highly creative and inspiring text prompt to create an artistic image."
            ""
        )
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7
        )
        logger.info(f"Сгенерированный промпт: {generated_prompt}")

        logger.info("Генерация изображения через Stability AI...")
        image_path = create_image_path()
        image_content = await stability_service.generate_image(generated_prompt)
        with open(image_path, "wb") as file:
            file.write(image_content)
        logger.info(f"Изображение сохранено в {image_path}")

        current_date_text = "S " + datetime.datetime.now().strftime("%d.%m.%Y")
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

import asyncio
import datetime
import os
from telethon import TelegramClient, functions, types
from config import TELETHON_API_ID, TELETHON_API_HASH, TELETHON_PEER
from services.gemini_service import GeminiService
from services.stability_service import StabilityService
from PIL import Image, ImageDraw, ImageFont
import logging
from utils.database import initialize_database, save_to_database

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Путь для хранения файлов
BASE_STORAGE_PATH = os.path.abspath("../storage")
IMAGES_PATH = os.path.join(BASE_STORAGE_PATH, "images")

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
        font_path = "../fonts/Roboto-Regular.ttf"
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
        "Create a highly creative and inspiring text prompt to create an artistic image."
        "Themes should be universe, fantasy, fiction, future or mystic."
        "All healthy themes that can touch a person's soul and inspire them."
        "Use text only and write in English."
    )

async def send_story():
    """
    Генерация и отправка сторис в Telegram.
    """
    # Инициализация Telethon клиента
    client = TelegramClient("telegram_story_session", TELETHON_API_ID, TELETHON_API_HASH)
    await client.start()

    gemini_service = GeminiService()
    stability_service = StabilityService()

    try:
        # Генерация текста
        user_prompt = generate_dynamic_prompt()
        logger.info(f"Генерация текста через Gemini Pro на тему: {user_prompt}")
        system_prompt = (
            "Create a highly creative and inspiring text prompt to create an artistic image."
        )
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=1.0
        )
        logger.info(f"Сгенерированный промпт: {generated_prompt}")

        # Генерация изображения
        logger.info("Генерация изображения через Stability AI...")
        image_path = create_image_path()
        image_content = await stability_service.generate_image(generated_prompt)
        with open(image_path, "wb") as file:
            file.write(image_content)
        logger.info(f"Изображение сохранено в {image_path}")

        # Добавление даты на изображение
        current_date_text = datetime.datetime.now().strftime("%d.%m.%Y")
        add_date_to_image(image_path, current_date_text)

        # Отправка сторис
        logger.info("Отправка сторис в Telegram...")
        result = await client(functions.stories.SendStoryRequest(
            peer=TELETHON_PEER,
            media=types.InputMediaUploadedPhoto(
                file=await client.upload_file(image_path),
                spoiler=False
            ),
            privacy_rules=[types.InputPrivacyValueAllowAll()]
        ))
        logger.info(f"Сторис успешно отправлена: {result}")

        # Сохранение данных в базу
        save_to_database(
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            generated_prompt=generated_prompt,
            image_path=image_path
        )

    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    initialize_database()
    asyncio.run(send_story())

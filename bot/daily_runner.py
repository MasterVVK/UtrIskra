import asyncio
import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID
from services.gemini_service import GeminiService
from services.stability_service import StabilityService
from PIL import Image, ImageDraw, ImageFont
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_date_to_image(image_path: str, date_text: str):
    """
    Добавляет дату на изображение.
    :param image_path: Путь к изображению.
    :param date_text: Текст даты.
    """
    try:
        # Открываем изображение
        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)

        # Настраиваем шрифт
        font_size = int(min(img.size) * 0.05)  # Размер шрифта зависит от размера изображения
        font = ImageFont.truetype("arial.ttf", font_size)  # Для Windows. На Linux замените шрифт, если нет arial

        # Позиция текста
        text_position = (img.size[0] - font_size * len(date_text) - 10, img.size[1] - font_size - 10)

        # Цвет текста
        text_color = (255, 255, 255)  # Белый

        # Добавляем тень для читаемости
        shadow_color = (0, 0, 0)  # Черный
        shadow_offset = 2
        draw.text(
            (text_position[0] + shadow_offset, text_position[1] + shadow_offset),
            date_text,
            font=font,
            fill=shadow_color,
        )

        # Добавляем текст
        draw.text(text_position, date_text, font=font, fill=text_color)

        # Сохраняем изображение
        img.save(image_path)
        logger.info(f"Дата '{date_text}' добавлена на изображение {image_path}")
    except Exception as e:
        logger.error(f"Ошибка при добавлении даты на изображение: {e}")

def generate_dynamic_prompt():
    """
    Генерирует универсальный промпт для Gemini Pro с использованием даты и заданной тематики.
    """
    current_date = datetime.datetime.now().strftime("%d %B %Y")  # Пример: 20 December 2024

    return (
        f"Today is {current_date}.\n"
        "Create a deeply inspiring and imaginative text prompt for generating an artistic image. The themes should include space, galaxy, universe, fantasy, science fiction, future, or mystery. "
        "The description should touch the soul and evoke strong emotions. Use the date as inspiration. Write the prompt in English."
    )

async def send_daily_story():
    """
    Генерация и отправка вдохновляющей картинки в Telegram-группу.
    """
    bot = Bot(token=TELEGRAM_TOKEN)
    gemini_service = GeminiService()
    stability_service = StabilityService()

    try:
        # Генерация текстового промпта
        prompt_text = generate_dynamic_prompt()
        logger.info(f"Генерация текста через Gemini Pro на тему: {prompt_text}")
        prompt = gemini_service.generate_prompt(
            system_prompt=(
                "Создайте высококреативную и вдохновляющую текстовую подсказку для создания художественного образа."
                "Темами должны быть вселенная, фэнтези, фантастика, будущее, мистика или на свое усмотрение." 
                "Все здоровые темы, которые могут затронут душу человека и вдохновить его."
                "На изображении нет флагов стран."
                "Используйте только текст и пишите на английском языке."
            ),
            user_prompt=prompt_text,
            temperature=1.0  # Высокая температура для максимальной креативности
        )
        logger.info(f"Сгенерированный промпт: {prompt}")

        # Генерация изображения
        logger.info("Генерация изображения через Stability AI...")
        image_content = await stability_service.generate_image(prompt)

        # Сохранение изображения
        image_path = "daily_story.png"
        with open(image_path, "wb") as file:
            file.write(image_content)
        logger.info(f"Изображение сохранено в {image_path}")

        # Добавление даты на изображение
        current_date_text = datetime.datetime.now().strftime("%d.%m.%Y")
        add_date_to_image(image_path, current_date_text)

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
    asyncio.run(send_daily_story())

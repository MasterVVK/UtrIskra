from aiogram import Bot, Dispatcher, types
from aiogram.types import FSInputFile
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID
from services.gemini_service import GeminiService
from services.stability_service import StabilityService
import asyncio
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StoryBot:
    """Класс для Telegram-бота с публикацией сторис."""

    def __init__(self):
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.gemini_service = GeminiService()
        self.stability_service = StabilityService()

    async def publish_story(self, topic: str = "цветы на рассвете"):
        """
        Генерация и публикация сторис в Telegram-группе.
        :param topic: Тема для генерации изображения.
        """
        try:
            logger.info("Генерация описания изображения через Gemini Pro...")
            prompt = self.gemini_service.generate_prompt(
                system_prompt="Создай описание изображения.",
                user_prompt=f"Создай описание изображения на тему '{topic}'."
            )

            logger.info(f"Сгенерированный промпт: {prompt}")

            logger.info("Генерация изображения через Stability AI...")
            image_content = await self.stability_service.generate_image(prompt)

            # Сохранение изображения
            image_path = "story.png"
            with open(image_path, "wb") as file:
                file.write(image_content)

            logger.info("Публикация сторис в Telegram...")
            await self.bot.send_photo(
                chat_id=TARGET_CHAT_ID,
                photo=FSInputFile(image_path),
                caption=f"Новая история на тему: {topic} 🌟"
            )

            logger.info("Сторис успешно опубликована!")
        except Exception as e:
            logger.error(f"Ошибка при публикации сторис: {e}")

    def register_handlers(self):
        """Регистрация команд бота."""
        self.dp.message.register(self.start_command, Command("start"))
        self.dp.message.register(self.help_command, Command("help"))
        self.dp.message.register(self.generate_story_command, Command("generate"))

    async def start_command(self, message: types.Message):
        """Обработчик команды /start."""
        await message.answer(
            "Привет! Я бот для публикации сторис.\n"
            "Команды:\n"
            "/generate <тема> - Создать и опубликовать сторис.\n"
            "/help - Помощь."
        )

    async def help_command(self, message: types.Message):
        """Обработчик команды /help."""
        await message.answer(
            "Я публикую сторис сгенерированные через Stability AI и Gemini Pro.\n"
            "Команды:\n"
            "/generate <тема> - Создать и опубликовать сторис на указанную тему.\n"
            "/start - Перезапуск бота."
        )

    async def generate_story_command(self, message: types.Message):
        """
        Обработчик команды /generate.
        Формат: /generate <тема>
        """
        # Извлекаем тему из команды
        command_parts = message.text.split(maxsplit=1)
        topic = command_parts[1] if len(command_parts) > 1 else None

        if not topic:
            await message.answer("Укажите тему для генерации. Например: /generate цветы на рассвете")
            return

        await message.answer(f"Генерация сторис на тему: {topic}. Подождите...")
        await self.publish_story(topic)
        await message.answer("Сторис успешно опубликована!")

    async def start(self):
        """Запуск бота."""
        logger.info("Запуск Telegram-бота...")
        self.register_handlers()
        await self.dp.start_polling(self.bot)


# Если скрипт запускается напрямую
if __name__ == "__main__":
    story_bot = StoryBot()
    asyncio.run(story_bot.start())

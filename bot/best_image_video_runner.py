import os
import asyncio
import datetime
import sys

# Добавляем корневую директорию в путь для импорта
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELETHON_API_ID, TELETHON_API_HASH, TELETHON_PEER, TELEGRAM_TOKEN, TARGET_CHAT_ID
from services.midjourney_service import MidjourneyService
from utils.image_utils import create_image_path, create_video_path, download_video
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def get_most_popular_image():
    """
    Анализирует сообщения в Telegram-группе за последнюю неделю
    и находит изображение с наибольшим количеством реакций.
    """
    # Создаём клиент Telethon для чтения сообщений
    # При первом запуске требуется интерактивная авторизация,
    # затем сессия сохраняется и используется автоматически
    # Используем абсолютный путь к файлу сессии, чтобы избежать проблем с рабочей директорией
    # Всегда используем корневую директорию проекта для хранения сессии
    session_file = '/home/user/UtrIskra/best_image_session'
    logger.info(f"Используется файл сессии: {session_file}.session")
    logger.info(f"Файл сессии существует: {os.path.exists(session_file + '.session')}")
    client = TelegramClient(session_file, TELETHON_API_ID, TELETHON_API_HASH)

    try:
        # Авторизуемся через пользовательский аккаунт
        # При первом запуске потребуется ввести номер телефона и код подтверждения
        # Затем сессия сохранится в файл best_image_session.session
        await client.start()
        logger.info("Telethon клиент запущен")

        # Получаем целевой чат/группу (преобразуем в int для числовых ID)
        peer_id = int(TELETHON_PEER) if TELETHON_PEER.lstrip('-').isdigit() else TELETHON_PEER
        entity = await client.get_entity(peer_id)
        logger.info(f"Подключение к группе: {entity.title if hasattr(entity, 'title') else TELETHON_PEER}")

        # Вычисляем дату недельной давности
        week_ago = datetime.datetime.now() - datetime.timedelta(days=7)
        logger.info(f"Поиск изображений с {week_ago.strftime('%Y-%m-%d %H:%M:%S')}")

        # Список для хранения сообщений с фото и их реакциями
        images_with_reactions = []

        # Получаем сообщения за последнюю неделю
        async for message in client.iter_messages(entity, offset_date=week_ago, limit=None):
            # Проверяем, что это фото
            if message.media and isinstance(message.media, MessageMediaPhoto):
                # Получаем реакции
                reactions_count = 0
                if message.reactions:
                    # Подсчитываем общее количество реакций
                    for reaction in message.reactions.results:
                        reactions_count += reaction.count

                # Сохраняем информацию о сообщении
                images_with_reactions.append({
                    'message_id': message.id,
                    'date': message.date,
                    'reactions_count': reactions_count,
                    'message': message
                })

                logger.info(
                    f"Найдено изображение: ID {message.id}, "
                    f"Дата: {message.date.strftime('%Y-%m-%d %H:%M')}, "
                    f"Реакций: {reactions_count}"
                )

        logger.info(f"Всего найдено изображений: {len(images_with_reactions)}")

        # Находим изображение с максимальным количеством реакций
        if not images_with_reactions:
            logger.info("Не найдено изображений с реакциями за последнюю неделю")
            return None

        # Сортируем по количеству реакций
        best_image = max(images_with_reactions, key=lambda x: x['reactions_count'])

        # Если нет реакций вообще, не обрабатываем
        if best_image['reactions_count'] == 0:
            logger.info("Все изображения имеют 0 реакций. Пропускаем обработку.")
            return None

        logger.info(
            f"\nСамое популярное изображение:\n"
            f"  ID: {best_image['message_id']}\n"
            f"  Дата: {best_image['date'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"  Реакций: {best_image['reactions_count']}"
        )

        return best_image

    finally:
        await client.disconnect()
        logger.info("Telethon клиент отключен")


async def send_best_image_video_story():
    """
    Главная функция: находит самое популярное изображение и оживляет его.
    На первом этапе - просто отправляет уведомление.
    """
    # Проверяем наличие необходимых переменных окружения
    if not TELETHON_API_ID or not TELETHON_API_HASH:
        logger.error(
            "\n❌ ОШИБКА: Не настроены переменные TELETHON_API_ID и TELETHON_API_HASH\n"
            "\nДля получения API ID и Hash:\n"
            "1. Перейдите на https://my.telegram.org/auth\n"
            "2. Войдите с помощью своего номера телефона\n"
            "3. Перейдите в 'API development tools'\n"
            "4. Создайте приложение и получите API ID и API Hash\n"
            "5. Добавьте их в файл .env:\n"
            "   TELETHON_API_ID=ваш_api_id\n"
            "   TELETHON_API_HASH=ваш_api_hash\n"
        )
        return

    bot = Bot(token=TELEGRAM_TOKEN)

    try:
        # Находим самое популярное изображение
        best_image = await get_most_popular_image()

        if best_image is None:
            logger.info("Нет подходящих изображений для обработки")
            return

        # Формируем сообщение об оживлении
        message_text = (
            f"🎬 Оживление популярного изображения!\n\n"
            f"📊 Статистика:\n"
            f"• ID сообщения: {best_image['message_id']}\n"
            f"• Дата публикации: {best_image['date'].strftime('%d.%m.%Y %H:%M')}\n"
            f"• Количество реакций: {best_image['reactions_count']}\n\n"
            f"⏳ Начинаю создание видео из этого изображения..."
        )

        # Отправляем уведомление в группу
        await bot.send_message(chat_id=TARGET_CHAT_ID, text=message_text)
        logger.info("Уведомление о создании видео отправлено!")

        # Скачивание изображения из Telegram
        logger.info("Скачивание популярного изображения...")
        image_path = create_image_path(prefix="best_image")

        # Повторно подключаемся к Telethon для скачивания
        session_file = '/home/user/UtrIskra/best_image_session'
        client = TelegramClient(session_file, TELETHON_API_ID, TELETHON_API_HASH)
        await client.start()

        try:
            # Получаем сообщение по ID
            peer_id = int(TELETHON_PEER) if TELETHON_PEER.lstrip('-').isdigit() else TELETHON_PEER
            message = await client.get_messages(peer_id, ids=best_image['message_id'])

            # Скачиваем изображение
            await client.download_media(message, file=image_path)
            logger.info(f"Изображение скачано: {image_path}")
        finally:
            await client.disconnect()

        # Отправляем исходное изображение в группу
        logger.info("Отправка исходного изображения в группу...")
        sent_photo = await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=FSInputFile(image_path))
        logger.info("Исходное изображение отправлено!")

        # Загружаем изображение на catbox.moe для получения публичного URL
        logger.info("Загрузка изображения на catbox.moe...")
        import requests
        with open(image_path, 'rb') as f:
            upload_response = requests.post(
                'https://catbox.moe/user/api.php',
                data={'reqtype': 'fileupload'},
                files={'fileToUpload': f}
            )
        upload_response.raise_for_status()
        image_url = upload_response.text.strip()
        logger.info(f"Публичный URL изображения: {image_url}")

        # Инициализируем сервис Midjourney
        midjourney_service = MidjourneyService()

        # Шаг 1: Загружаем изображение в Midjourney через image-to-image с минимальными изменениями
        logger.info("Загрузка изображения в Midjourney (image-to-image)...")

        # Создаем image-to-image с минимальным промптом для обработки изображения (с повторами)
        image_result = midjourney_service.execute_with_retry(
            task_func=lambda: midjourney_service.create_image_to_image_task(
                file_url=image_url,
                prompt="high quality, detailed",
                aspect_ratio="16:9"
            ),
            task_name="image-to-image",
            max_retries=2,
            retry_delay=300  # 5 минут
        )

        # Шаг 2: Создаем видео используя обработанное изображение (с повторами)
        logger.info("Создание видео из обработанного изображения...")

        video_result = midjourney_service.execute_with_retry(
            task_func=lambda: midjourney_service.create_video_task(
                file_url=image_url,
                prompt="gentle movement, cinematic camera motion",
                motion="high",
                video_batch_size=1,
                task_type="image-to-video"
            ),
            task_name="image-to-video",
            max_retries=2,
            retry_delay=300  # 5 минут
        )

        # Получаем URL видео
        video_urls = video_result.get("data", {}).get("output", {}).get("video_urls", [])
        if not video_urls:
            raise ValueError(f"Не удалось получить URL видео. Структура ответа: {video_result}")

        video_url = video_urls[0]
        logger.info(f"Получен URL видео: {video_url}")

        # Скачивание видео
        video_path = create_video_path(prefix="best_image_video")
        logger.info("Скачивание видео...")
        download_video(video_url, video_path)

        # Отправка видео в Telegram
        logger.info("Отправка видео в Telegram...")
        await bot.send_video(chat_id=TARGET_CHAT_ID, video=FSInputFile(video_path))
        logger.info("✅ Видео успешно отправлено!")

    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(send_best_image_video_story())

import os
from telethon import TelegramClient
from config import TELETHON_API_ID, TELETHON_API_HASH

# Название файла для хранения сессии
SESSION_FILE = "telegram_story_session"


def main():
    """
    Создание или использование существующей сессии Telethon.
    """
    # Создаем клиента
    client = TelegramClient(SESSION_FILE, TELETHON_API_ID, TELETHON_API_HASH)

    try:
        # Если файл сессии существует, используем его
        if os.path.exists(f"{SESSION_FILE}.session"):
            print(f"Файл сессии '{SESSION_FILE}.session' найден. Используем существующую сессию.")
        else:
            print("Файл сессии не найден. Запускаем процесс авторизации...")

        client.start(password='')  # Автоматический вход или запрос авторизации
        print("Клиент успешно запущен!")

        # Вывод информации об авторизованном пользователе
        user_info = client.get_me()
        print("Информация о пользователе:")
        print(user_info.stringify())

        print(f"Сессия сохранена в файле: {SESSION_FILE}.session")
    except Exception as e:
        print(f"Ошибка: {e}")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()

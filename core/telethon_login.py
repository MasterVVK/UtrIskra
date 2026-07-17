"""Разовая интерактивная авторизация Telethon-сессии для задачи best_image_video.

Запуск на сервере: .venv/bin/python -m core.telethon_login
Спросит номер телефона и код подтверждения, сохранит сессию в
best_image_session.session в корне проекта.
"""
import os

from telethon import TelegramClient

from config import TELETHON_API_ID, TELETHON_API_HASH

# тот же путь, что использует core/pipeline.py (без импорта всего пайплайна)
TELETHON_SESSION = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "best_image_session")

if __name__ == "__main__":
    if not (TELETHON_API_ID and TELETHON_API_HASH):
        raise SystemExit("TELETHON_API_ID / TELETHON_API_HASH не заданы в .env")
    with TelegramClient(TELETHON_SESSION, TELETHON_API_ID, TELETHON_API_HASH) as client:
        me = client.loop.run_until_complete(client.get_me())
        print(f"Авторизовано: {me.first_name} (id {me.id}). "
              f"Сессия сохранена: {TELETHON_SESSION}.session")

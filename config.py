import os
from dotenv import load_dotenv

load_dotenv()

# Stability AI API Key
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY")

# Gemini Pro API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Target Group Chat ID
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")

PROXY_URL = os.getenv("PROXY_URL")
GEMINI_API_KEYS = os.getenv("GEMINI_API_KEYS").split(",")

# Telethon API Credentials
TELETHON_API_ID = os.getenv("TELETHON_API_ID")  # Ваш API ID для Telethon
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH")  # Ваш API HASH для Telethon
TELETHON_PEER = os.getenv("TELETHON_PEER")  # Целевое сообщество или канал

# Storage Paths
BASE_STORAGE_PATH = os.getenv("BASE_STORAGE_PATH")  # Основной путь к storage
IMAGES_PATH = os.path.join(BASE_STORAGE_PATH, "images")  # Путь для изображений
DB_PATH = os.getenv("DB_PATH")  # Путь к базе данных
FONTS_PATH = os.getenv("FONTS_PATH")  # Абсолютный путь к шрифту Roboto

# Yandex Cloud Configuration
FOLDER_ID = os.getenv("FOLDER_ID")           # Идентификатор папки в Yandex Cloud
OAUTH_TOKEN = os.getenv("OAUTH_TOKEN")         # OAuth-токен для получения IAM-токена

MIDJOURNEY_API_TOKEN = os.getenv("MIDJOURNEY_API_TOKEN")

# Flux API Key
BFL_API_KEY = os.getenv("BFL_API_KEY")

KANDINSKY_API_KEY = os.getenv("KANDINSKY_API_KEY")
KANDINSKY_SECRET_KEY = os.getenv("KANDINSKY_SECRET_KEY")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

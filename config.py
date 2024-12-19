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
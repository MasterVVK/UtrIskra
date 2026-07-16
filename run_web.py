"""Точка входа веб-приложения UtrIskra.

Хост и порт настраиваются через WEB_HOST / WEB_PORT в .env
(по умолчанию 0.0.0.0:8090). Запускать строго в один процесс —
внутри приложения работает APScheduler.
"""
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    uvicorn.run(
        "webapp.app:app",
        host=os.getenv("WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("WEB_PORT", "8090")),
    )

import sqlite3
import os
import logging
from config import BASE_STORAGE_PATH

# Настройка логирования
logger = logging.getLogger(__name__)

# Путь к базе данных
#BASE_STORAGE_PATH = os.path.abspath("../storage")  # Абсолютный путь к storage
DB_PATH = os.path.join(BASE_STORAGE_PATH, "database", "daily_images.db")

def initialize_database():
    """
    Создает таблицу в базе данных, если она не существует.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)  # Создаем папку для базы, если она отсутствует
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    system_prompt TEXT NOT NULL,
                    user_prompt TEXT NOT NULL,
                    generated_prompt TEXT NOT NULL,
                    image_path TEXT NOT NULL
                )
            """)
            conn.commit()
            logger.info("Таблица базы данных успешно инициализирована.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")

def save_to_database(date, system_prompt, user_prompt, generated_prompt, image_path):
    """
    Сохраняет данные о сгенерированном изображении в базу данных.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO daily_images (date, system_prompt, user_prompt, generated_prompt, image_path)
                VALUES (?, ?, ?, ?, ?)
            """, (date, system_prompt, user_prompt, generated_prompt, image_path))
            conn.commit()
            logger.info("Данные успешно сохранены в базу данных.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка сохранения данных в базу: {e}")

import sqlite3
import os
import logging

# Настройка логирования
logger = logging.getLogger(__name__)

# Путь к базе данных
DB_PATH = "daily_images.db"

def initialize_database():
    """
    Создает таблицу в базе данных, если она не существует.
    """
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
                    image_data BLOB NOT NULL
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

            # Чтение изображения как бинарных данных
            with open(image_path, "rb") as img_file:
                image_data = img_file.read()

            cursor.execute("""
                INSERT INTO daily_images (date, system_prompt, user_prompt, generated_prompt, image_data)
                VALUES (?, ?, ?, ?, ?)
            """, (date, system_prompt, user_prompt, generated_prompt, image_data))
            conn.commit()
            logger.info("Данные успешно сохранены в базу данных.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка сохранения данных в базу: {e}")

def load_image_from_database(image_id, output_path):
    """
    Извлекает изображение из базы данных и сохраняет в файл.
    :param image_id: Идентификатор записи в базе данных.
    :param output_path: Путь для сохранения изображения.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT image_data FROM daily_images WHERE id = ?", (image_id,))
            result = cursor.fetchone()
            if result:
                with open(output_path, "wb") as img_file:
                    img_file.write(result[0])
                logger.info(f"Изображение с ID {image_id} сохранено в {output_path}")
            else:
                logger.warning(f"Изображение с ID {image_id} не найдено.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка извлечения изображения из базы данных: {e}")

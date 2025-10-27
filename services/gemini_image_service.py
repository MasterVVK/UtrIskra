import os
import sys
import logging
from google import genai
from google.genai import types
from config import GEMINI_API_KEYS

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GeminiImageService:
    """
    Класс для взаимодействия с API генерации изображений Gemini с использованием библиотеки google-genai.
    """

    def __init__(self):
        if not GEMINI_API_KEYS:
            raise ValueError("GEMINI_API_KEYS отсутствуют. Проверьте файл config.py.")
        
        self.api_keys = GEMINI_API_KEYS
        self.current_key_index = 0

    def switch_to_next_key(self):
        """Переключает на следующий ключ."""
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        logger.info(f"[INFO] Переключение на следующий ключ Gemini.")

    def generate_image(self, prompt: str) -> bytes:
        """
        Генерирует изображение на основе текстового промпта, используя google-genai.
        """
        for _ in range(len(self.api_keys)):
            try:
                api_key = self.api_keys[self.current_key_index]
                client = genai.Client(api_key=api_key)

                model_name = "gemini-2.5-flash-image-preview"
                logger.info(f"Запрос на генерацию изображения с моделью {model_name} и промптом: {prompt}")

                response_stream = client.models.generate_content_stream(
                    model=model_name,
                    contents=[prompt],
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"]
                    ),
                )

                for chunk in response_stream:
                    if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                        part = chunk.candidates[0].content.parts[0]
                        if part.inline_data and part.inline_data.data:
                            logger.info("Изображение успешно сгенерировано.")
                            return part.inline_data.data

                raise ValueError("Не удалось получить данные изображения из потока API.")

            except Exception as e:
                logger.error(f"Ошибка при работе с Gemini API: {e}")
                self.switch_to_next_key()
                continue

        logger.critical("[CRITICAL] Все API-ключи Gemini недействительны или исчерпаны. Завершение работы.")
        sys.exit(1)

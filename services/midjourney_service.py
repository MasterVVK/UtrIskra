import httpx
import logging
import time
from config import MIDJOURNEY_API_TOKEN

logger = logging.getLogger(__name__)

class MidjourneyService:
    """Сервис для взаимодействия с API Kolersky Midjourney (v1)."""

    BASE_URL = "https://api.kolersky.com/v1/midjourney"
    STATUS_URL = "https://api.kolersky.com/v1/status"

    def __init__(self):
        if not MIDJOURNEY_API_TOKEN:
            raise ValueError("MIDJOURNEY_API_TOKEN отсутствует. Проверьте файл config.py.")
        self.headers = {"Authorization": f"Bearer {MIDJOURNEY_API_TOKEN}"}
        self.client = httpx.Client(headers=self.headers, timeout=30)

    def create_imagine_task(self, prompt: str, aspect_ratio: str = "1:1", speed: str = "relaxed") -> dict:
        """Создание задачи генерации изображения (text-to-image)."""
        url = f"{self.BASE_URL}/generate"
        payload = {
            "taskType": "text-to-image",
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "speed": speed
        }
        response = self.client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def upload_image(self, image_path: str, extension: str = None) -> str:
        """
        Загружает изображение напрямую в API и возвращает CDN URL.

        Args:
            image_path: Путь к файлу изображения
            extension: Расширение файла (png, jpg, jpeg, webp). Если None, определяется автоматически

        Returns:
            URL загруженного изображения на CDN
        """
        import base64
        import os

        # Определяем расширение файла
        if extension is None:
            extension = os.path.splitext(image_path)[1].lstrip('.').lower()
            if extension == 'jpg':
                extension = 'jpeg'

        # Читаем файл и конвертируем в base64
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        url = f"{self.BASE_URL}/image/upload"
        payload = {
            "image": image_data,
            "extension": extension
        }

        logger.info(f"Загрузка изображения {image_path} (расширение: {extension})...")
        response = self.client.post(url, json=payload)
        response.raise_for_status()
        result = response.json()

        if "url" not in result:
            raise ValueError(f"URL отсутствует в ответе: {result}")

        cdn_url = result["url"]
        logger.info(f"✅ Изображение загружено: {cdn_url}")
        return cdn_url

    def create_image_to_image_task(self, file_url: str, prompt: str, aspect_ratio: str = "16:9") -> dict:
        """Создание задачи image-to-image (минимальные изменения изображения)."""
        url = f"{self.BASE_URL}/generate"
        payload = {
            "taskType": "image-to-image",
            "prompt": prompt,
            "fileUrl": file_url,
            "aspectRatio": aspect_ratio
        }
        logger.info(f"Отправка запроса image-to-image: {payload}")
        response = self.client.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        logger.info(f"Ответ API на image-to-image: {result}")
        return result

    def create_video_task(self, file_url: str, prompt: str = "", motion: str = "high",
                         video_batch_size: int = 1, task_type: str = "image-to-video") -> dict:
        """
        Создание задачи генерации видео из изображения.

        Args:
            file_url: URL изображения для создания видео
            prompt: Опциональный промпт для управления движением
            motion: Уровень движения "low" или "high" (по умолчанию "high")
            video_batch_size: Количество видео для генерации 1, 2 или 4 (по умолчанию 1)
            task_type: Тип задачи "image-to-video" или "image-to-video-hd"
        """
        url = f"{self.BASE_URL}/generate"
        payload = {
            "taskType": task_type,
            "fileUrl": file_url,
            "motion": motion,
            "videoBatchSize": video_batch_size
        }
        if prompt:
            payload["prompt"] = prompt

        logger.info(f"Отправка запроса на создание видео: {payload}")
        response = self.client.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        logger.info(f"Ответ API на создание видео: {result}")
        return result

    def get_task_status(self, request_id: str) -> dict:
        """Получение статуса задачи."""
        url = f"{self.STATUS_URL}?requestId={request_id}"
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    def wait_for_task_completion(self, request_id: str, timeout: int = 300) -> dict:
        """Ожидание завершения задачи."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            result = self.get_task_status(request_id)
            # API возвращает статус на верхнем уровне
            status = result.get("status")
            if status == "success":
                return result
            elif status == "error":
                # failReason может быть: верхнем уровне, в output, или в data.output
                fail_reason = (
                    result.get("failReason") or
                    result.get("output", {}).get("failReason") or
                    result.get("data", {}).get("output", {}).get("failReason", "Unknown error")
                )
                logger.error(f"Полный ответ API с ошибкой: {result}")
                raise Exception(f"Задача {request_id} завершилась с ошибкой: {fail_reason}")
            time.sleep(5)
        raise TimeoutError(f"Задача {request_id} не завершилась за {timeout} секунд.")

    def execute_with_retry(self, task_func, task_name: str, max_retries: int = 2, retry_delay: int = 300):
        """
        Выполняет задачу с повторными попытками при ошибках.

        Args:
            task_func: Функция для выполнения (должна возвращать request_id)
            task_name: Название задачи для логирования
            max_retries: Максимальное количество попыток (по умолчанию 2: первая + 1 повтор)
            retry_delay: Задержка между попытками в секундах (по умолчанию 300 = 5 минут)

        Returns:
            Результат успешного выполнения задачи

        Raises:
            Exception: Если все попытки исчерпаны
        """
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Попытка {attempt}/{max_retries} для задачи: {task_name}")

                # Выполняем функцию создания задачи
                task_result = task_func()

                if "requestId" not in task_result:
                    logger.error(f"Ключ 'requestId' отсутствует в ответе: {task_result}")
                    raise KeyError("Ключ 'requestId' отсутствует в ответе.")

                request_id = task_result["requestId"]
                logger.info(f"Ожидание завершения задачи {task_name} (requestId: {request_id})...")

                # Ожидаем завершения
                result = self.wait_for_task_completion(request_id)
                logger.info(f"✅ Задача {task_name} успешно завершена!")
                return result

            except Exception as e:
                error_message = str(e)
                logger.error(f"❌ Попытка {attempt}/{max_retries} не удалась: {error_message}")

                # Если это последняя попытка - прокидываем ошибку дальше
                if attempt >= max_retries:
                    logger.error(f"🛑 Все попытки ({max_retries}) исчерпаны для задачи: {task_name}")
                    raise

                # Иначе ждем перед следующей попыткой
                logger.info(f"⏳ Ожидание {retry_delay} секунд перед следующей попыткой...")
                time.sleep(retry_delay)
                logger.info(f"🔄 Начинаем повторную попытку...")

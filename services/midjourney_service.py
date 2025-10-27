import httpx
import logging
from config import MIDJOURNEY_API_TOKEN

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

    def get_task_status(self, request_id: str) -> dict:
        """Получение статуса задачи."""
        url = f"{self.STATUS_URL}?requestId={request_id}"
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    def wait_for_task_completion(self, request_id: str, timeout: int = 300) -> dict:
        """Ожидание завершения задачи."""
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            result = self.get_task_status(request_id)
            # API возвращает статус на верхнем уровне
            status = result.get("status")
            if status == "success":
                return result
            elif status == "error":
                fail_reason = result.get("data", {}).get("output", {}).get("failReason", "Unknown error")
                raise Exception(f"Задача {request_id} завершилась с ошибкой: {fail_reason}")
            time.sleep(5)
        raise TimeoutError(f"Задача {request_id} не завершилась за {timeout} секунд.")

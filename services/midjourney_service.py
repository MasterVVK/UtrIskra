import httpx
import logging
from config import MIDJOURNEY_API_TOKEN

class MidjourneyService:
    """Сервис для взаимодействия с API Kolersky Midjourney."""

    BASE_URL = "https://api.kolersky.com/api/midjourney"

    def __init__(self):
        if not MIDJOURNEY_API_TOKEN:
            raise ValueError("MIDJOURNEY_API_TOKEN отсутствует. Проверьте файл config.py.")
        self.headers = {"x-token": MIDJOURNEY_API_TOKEN}
        self.client = httpx.Client(headers=self.headers, timeout=30)

    def create_imagine_task(self, prompt: str, aspect_ratio: str = "1:1", process_mode: str = "relax") -> dict:
        """Создание задачи Imagine."""
        url = f"{self.BASE_URL}/imagine"
        payload = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "process_mode": process_mode
        }
        response = self.client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def get_task_status(self, task_id: str) -> dict:
        """Получение статуса задачи."""
        url = f"{self.BASE_URL}/get_task?task_id={task_id}"
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    def wait_for_task_completion(self, task_id: str, timeout: int = 300) -> dict:
        """Ожидание завершения задачи."""
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.get_task_status(task_id)
            if status["status"] == "completed":
                return status
            time.sleep(5)
        raise TimeoutError(f"Задача {task_id} не завершилась за {timeout} секунд.")

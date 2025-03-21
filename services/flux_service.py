import httpx
import random
import logging
import asyncio  # Добавляем импорт asyncio
from config import BFL_API_KEY

logger = logging.getLogger(__name__)


class FluxService:
    """Асинхронный класс для взаимодействия с FLUX API."""

    BASE_URL = "https://api.bfl.ml/v1"
    FLUX_ENDPOINT = "/flux-pro-1.1-ultra"

    def __init__(self, api_key: str = BFL_API_KEY, timeout: int = 60):
        """
        Инициализация FluxService.
        :param api_key: API-ключ для взаимодействия с FLUX API.
        :param timeout: Тайм-аут для запросов.
        """
        if not api_key:
            raise ValueError("Не указан API-ключ FLUX. Убедитесь, что 'BFL_API_KEY' задан в config.py.")
        self.api_key = api_key
        self.headers = {
            "accept": "application/json",
            "x-key": self.api_key,
            "Content-Type": "application/json",
        }
        self.timeout = timeout

    async def create_request(self, prompt: str, width: int = 1344, height: int = 768) -> str:
        """
        Создает запрос на генерацию изображения.
        :param prompt: Описание изображения.
        :param width: Ширина изображения.
        :param height: Высота изображения.
        :return: ID задачи для получения результата.
        """
        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "aspect_ratio": "16:9",
            "steps": 50,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.BASE_URL}{self.FLUX_ENDPOINT}",
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()
                return response.json()["id"]
            except httpx.RequestError as e:
                logger.error(f"Ошибка подключения к Flux API: {e}")
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"Ошибка статуса HTTP: {e.response.status_code} - {e.response.text}")
                raise

    async def poll_for_result(self, request_id: str, delay: int = 5, attempts: int = 60) -> str:
        """
        Ожидает завершения задачи и возвращает URL результата.
        :param request_id: ID задачи.
        :param delay: Интервал между попытками (в секундах).
        :param attempts: Максимальное количество попыток.
        :return: Ссылка на результат (URL изображения).
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(attempts):
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/get_result",
                        headers=self.headers,
                        params={"id": request_id},
                    )
                    response.raise_for_status()
                    result_data = response.json()

                    if result_data["status"] == "Ready":
                        return result_data["result"]["sample"]
                    elif result_data["status"] not in {"Pending", "Processing"}:
                        raise ValueError(f"Ошибка статуса задачи: {result_data['status']}")

                    logger.info(f"Задача {request_id} обрабатывается. Попытка {attempt + 1}/{attempts}")
                    await asyncio.sleep(delay)
                except httpx.RequestError as e:
                    logger.error(f"Ошибка подключения к Flux API: {e}")
                except Exception as e:
                    logger.error(f"Ошибка при ожидании результата: {e}")

        raise TimeoutError(f"Задача {request_id} не завершилась за {attempts * delay} секунд.")

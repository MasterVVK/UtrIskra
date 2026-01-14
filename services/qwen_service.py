import httpx
import logging
import asyncio
from config import QWEN_API_URL

logger = logging.getLogger(__name__)


class QwenService:
    """Асинхронный класс для взаимодействия с Qwen-Image API."""

    def __init__(self, base_url: str = QWEN_API_URL, timeout: int = 60):
        """
        Инициализация QwenService.
        :param base_url: Базовый URL API.
        :param timeout: Тайм-аут для запросов.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
        }

    async def health_check(self) -> dict:
        """
        Проверка доступности API и статуса модели.
        :return: Словарь с информацией о здоровье сервиса.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/api/v1/health",
                    headers=self.headers,
                )
                response.raise_for_status()
                return response.json()
            except httpx.RequestError as e:
                logger.error(f"Ошибка подключения к Qwen API: {e}")
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"Ошибка статуса HTTP: {e.response.status_code} - {e.response.text}")
                raise

    async def create_task(
        self,
        prompt: str,
        negative_prompt: str = "",
        aspect_ratio: str = "16:9",
        num_inference_steps: int = 50,
        cfg_scale: float = 4.0,
        seed: int = None,
    ) -> str:
        """
        Создает задачу на генерацию изображения.
        :param prompt: Промпт для генерации.
        :param negative_prompt: Негативный промпт.
        :param aspect_ratio: Соотношение сторон (1:1, 16:9, 9:16, 4:3, 3:4).
        :param num_inference_steps: Количество шагов деноизинга (1-100).
        :param cfg_scale: Guidance scale (1-20).
        :param seed: Сид для воспроизводимости.
        :return: ID задачи.
        """
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "aspect_ratio": aspect_ratio,
            "num_inference_steps": num_inference_steps,
            "cfg_scale": cfg_scale,
        }
        if seed is not None:
            payload["seed"] = seed

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/v1/generate",
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"Задача создана: {result['task_id']}, позиция в очереди: {result['queue_position']}")
                return result["task_id"]
            except httpx.RequestError as e:
                logger.error(f"Ошибка подключения к Qwen API: {e}")
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"Ошибка статуса HTTP: {e.response.status_code} - {e.response.text}")
                raise

    async def get_task_status(self, task_id: str) -> dict:
        """
        Получает статус задачи генерации.
        :param task_id: ID задачи.
        :return: Словарь с информацией о задаче.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/api/v1/tasks/{task_id}",
                    headers=self.headers,
                )
                response.raise_for_status()
                return response.json()
            except httpx.RequestError as e:
                logger.error(f"Ошибка подключения к Qwen API: {e}")
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"Ошибка статуса HTTP: {e.response.status_code} - {e.response.text}")
                raise

    async def wait_for_completion(
        self,
        task_id: str,
        timeout: int = 1200,
        poll_interval: int = 10,
    ) -> dict:
        """
        Ожидает завершения задачи с polling.
        :param task_id: ID задачи.
        :param timeout: Максимальное время ожидания в секундах.
        :param poll_interval: Интервал между проверками в секундах.
        :return: Информация о завершённой задаче.
        """
        attempts = timeout // poll_interval

        for attempt in range(attempts):
            task_info = await self.get_task_status(task_id)
            status = task_info["status"]

            if status == "completed":
                logger.info(
                    f"Задача {task_id} завершена за {task_info.get('generation_time_seconds', '?')} сек"
                )
                return task_info
            elif status == "failed":
                error_msg = task_info.get("error", "Неизвестная ошибка")
                logger.error(f"Задача {task_id} завершилась с ошибкой: {error_msg}")
                raise RuntimeError(f"Генерация не удалась: {error_msg}")
            else:
                queue_pos = task_info.get("queue_position")
                pos_info = f", позиция в очереди: {queue_pos}" if queue_pos else ""
                logger.info(
                    f"Задача {task_id}: статус '{status}'{pos_info}. "
                    f"Попытка {attempt + 1}/{attempts}"
                )
                await asyncio.sleep(poll_interval)

        raise TimeoutError(f"Задача {task_id} не завершилась за {timeout} секунд")

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        aspect_ratio: str = "16:9",
        num_inference_steps: int = 50,
        cfg_scale: float = 4.0,
        seed: int = None,
        timeout: int = 1200,
        poll_interval: int = 10,
    ) -> str:
        """
        Полный цикл генерации изображения.
        :return: URL сгенерированного изображения.
        """
        task_id = await self.create_task(
            prompt=prompt,
            negative_prompt=negative_prompt,
            aspect_ratio=aspect_ratio,
            num_inference_steps=num_inference_steps,
            cfg_scale=cfg_scale,
            seed=seed,
        )

        task_info = await self.wait_for_completion(
            task_id=task_id,
            timeout=timeout,
            poll_interval=poll_interval,
        )

        image_url = task_info.get("image_url")
        if not image_url:
            raise RuntimeError("Изображение сгенерировано, но URL не получен")

        # Формируем полный URL если это относительный путь
        if image_url.startswith("/"):
            image_url = f"{self.base_url}{image_url}"

        return image_url

"""Универсальный провайдер self-hosted генераторов с task-API.

Один класс обслуживает qwen, zimage, ernie, hidream и любые будущие серверы
с тем же контрактом:
  POST {base}/api/v1/generate  {prompt, ...параметры} -> {task_id, queue_position}
  GET  {base}/api/v1/tasks/{task_id} -> {status: completed|failed|..., image_url, error}
  GET  {base}/api/v1/health

Параметры генерации (steps, cfg/guidance, use_pe, model, ...) задаются схемой
`params` в конфиге инстанса — payload собирается из неё как есть.
"""
import asyncio
import logging

import httpx

from providers.image.base import ImageProvider, download_bytes

logger = logging.getLogger(__name__)


class LocalTaskProvider(ImageProvider):
    type = "local_task"

    @property
    def base_url(self):
        return self.config.get("base_url", "").rstrip("/")

    async def generate(self, prompt, params):
        payload = {"prompt": prompt, **self.apply_defaults(params)}
        poll_interval = float(self.config.get("poll_interval", 10))
        total_timeout = float(self.config.get("timeout", 1200))
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.base_url}/api/v1/generate", json=payload)
            response.raise_for_status()
            created = response.json()
            task_id = created["task_id"]
            logger.info("«%s»: задача %s создана, очередь: %s",
                        self.name, task_id, created.get("queue_position", "—"))

            attempts = max(1, int(total_timeout // poll_interval))
            for attempt in range(attempts):
                status_response = await client.get(f"{self.base_url}/api/v1/tasks/{task_id}")
                status_response.raise_for_status()
                info = status_response.json()
                status = info.get("status")
                if status == "completed":
                    logger.info("«%s»: задача %s готова за %s с", self.name, task_id,
                                info.get("generation_time_seconds", "?"))
                    image_url = info.get("image_url")
                    if not image_url:
                        raise RuntimeError(f"«{self.name}»: задача завершена, но image_url пуст")
                    if image_url.startswith("/"):
                        image_url = self.base_url + image_url
                    return await download_bytes(image_url)
                if status == "failed":
                    raise RuntimeError(f"«{self.name}»: генерация не удалась: "
                                       f"{info.get('error', 'неизвестная ошибка')}")
                logger.info("«%s»: задача %s — %s (попытка %d/%d)",
                            self.name, task_id, status, attempt + 1, attempts)
                await asyncio.sleep(poll_interval)
        raise TimeoutError(f"«{self.name}»: задача {task_id} не завершилась за {total_timeout:.0f} с")

    async def health(self):
        if not self.base_url:
            return False, "не задан base_url"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/api/v1/health")
            if response.status_code == 200:
                data = response.json()
                brief = ", ".join(f"{k}={v}" for k, v in list(data.items())[:3]) or "ok"
                return True, brief
            return False, f"HTTP {response.status_code}"
        except Exception as exc:
            return False, str(exc)

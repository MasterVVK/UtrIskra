"""Провайдер единого шлюза images-api (br-01).

Четыре self-hosted сервиса (qwen 8000, zimage 8001, ernie 8002, hidream 8003)
заменены одним шлюзом на 8010: общий контракт, очередь, арбитраж VRAM и два
GPU-узла (br-01, nv-02). Класс говорит с ним и покрывает все модели реестра.

  POST {base}/api/v1/generate         {model, prompt, ...} -> {task_id, status, queue_position}
  GET  {base}/api/v1/tasks/{id}/wait  ждать завершения без цикла поллинга
  DELETE {base}/api/v1/tasks/{id}     отмена (шлём, если сдались по таймауту)
  GET  {base}/api/v1/images/{path}    PNG по подписанной ссылке из image_url
  GET  {base}/readyz                  здоровье шлюза и узлов

Отличия от прежних сервисов: обязателен ключ `X-API-Key`, модель задаётся
плоским id из реестра шлюза (qwen-image, z-image-turbo, z-image-base,
ernie-image, ernie-image-turbo, hidream-o1), CFG у всех называется
`guidance_scale`. Набор параметров инстанса, как и раньше, описывает `params`
в конфиге — своя схема на каждую модель.
"""
import asyncio
import contextlib
import logging
import os
import time

import httpx

from providers.image.base import ImageProvider

logger = logging.getLogger(__name__)

# Статусы шлюза, после которых ждать больше нечего.
TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class ImagesApiProvider(ImageProvider):
    type = "images_api"

    @property
    def base_url(self):
        return self.config.get("base_url", "").rstrip("/")

    @property
    def model(self):
        return self.config.get("model", "")

    def _headers(self):
        key = os.getenv(self.config.get("api_key_env", "IMAGES_API_KEY"), "")
        return {"X-API-Key": key} if key else {}

    def describe(self):
        return f"{self.base_url} · {self.model}" if self.model else self.base_url

    async def generate(self, prompt, params):
        if not self.base_url:
            raise RuntimeError(f"«{self.name}»: не задан base_url")
        values = self.apply_defaults(params)
        # Модель можно зафиксировать в инстансе и/или выбирать в задаче
        # (у zimage и ernie есть turbo-варианты) — значение из задачи главнее.
        model = values.pop("model", None) or self.model
        if not model:
            raise RuntimeError(f"«{self.name}»: не задана модель (config.model или параметр model)")
        payload = {"model": model, "prompt": prompt}
        for key, value in values.items():
            # Пустая строка — это «не задано»: у hidream непустой negative_prompt
            # шлюз отвергает с 422, а не игнорирует молча.
            if value == "" or value is None:
                continue
            payload[key] = value

        total_timeout = float(self.config.get("timeout", 1800))
        # Длина одного ожидания: /wait возвращает текущее состояние по истечении
        # таймаута, поэтому цикл нужен только чтобы писать в лог, что происходит.
        wait_chunk = float(self.config.get("wait_chunk", 60))
        deadline = time.monotonic() + total_timeout

        async with httpx.AsyncClient(timeout=60, headers=self._headers()) as client:
            response = await client.post(f"{self.base_url}/api/v1/generate", json=payload)
            self._raise_for_error(response, "постановка задачи")
            created = response.json()
            task_id = created["task_id"]
            logger.info("«%s»: %s → задача %s, очередь: %s (%s)", self.name, model, task_id,
                        created.get("queue_position", "—"), created.get("message", ""))

            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"«{self.name}»: задача {task_id} не завершилась "
                                           f"за {total_timeout:.0f} с")
                    chunk = max(1.0, min(wait_chunk, remaining))
                    status_response = await client.get(
                        f"{self.base_url}/api/v1/tasks/{task_id}/wait",
                        params={"timeout": chunk}, timeout=chunk + 30)
                    self._raise_for_error(status_response, f"ожидание задачи {task_id}")
                    info = status_response.json()
                    status = info.get("status")

                    if status == "completed":
                        logger.info("«%s»: задача %s готова за %s с (%sx%s, узел %s)",
                                    self.name, task_id, info.get("generation_time_seconds", "?"),
                                    info.get("width"), info.get("height"), info.get("node"))
                        return await self._fetch_image(client, info)
                    if status in TERMINAL_STATUSES:
                        raise RuntimeError(
                            f"«{self.name}»: генерация не удалась ({status}"
                            f"{'/' + info['error_code'] if info.get('error_code') else ''}): "
                            f"{info.get('error') or 'причина не указана'}")

                    logger.info("«%s»: задача %s — %s%s", self.name, task_id, status,
                                self._progress_hint(info))
            except (Exception, asyncio.CancelledError):
                # Бросить задачу как есть нельзя: она держит карту эксклюзивно,
                # а после нашего ухода результат всё равно некому забрать.
                await self._cancel(task_id)
                raise

    async def _fetch_image(self, client, info):
        image_url = info.get("image_url")
        if not image_url:
            raise RuntimeError(f"«{self.name}»: задача завершена, но image_url пуст")
        if image_url.startswith("/"):
            image_url = self.base_url + image_url
        response = await client.get(image_url, timeout=180, follow_redirects=True)
        self._raise_for_error(response, "скачивание изображения")
        return response.content

    async def _cancel(self, task_id):
        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=15, headers=self._headers()) as client:
                response = await client.delete(f"{self.base_url}/api/v1/tasks/{task_id}")
            if response.status_code < 400:
                logger.info("«%s»: задача %s отменена", self.name, task_id)

    @staticmethod
    def _progress_hint(info):
        """Хвост строки лога: очередь и почему задача ждёт."""
        if info.get("status") == "waiting_vram":
            return ", ждём свободную VRAM"
        position = info.get("queue_position")
        return f", в очереди {position}" if position else ""

    def _raise_for_error(self, response, stage):
        if response.status_code < 400:
            return
        raise RuntimeError(f"«{self.name}»: {stage} — HTTP {response.status_code}: "
                           f"{self._error_text(response)}")

    @staticmethod
    def _error_text(response):
        """Оба конверта шлюза: {"error": {code, message}} и pydantic-овский detail."""
        try:
            body = response.json()
        except ValueError:
            return response.text.strip()[:300]
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                code = error.get("code") or ""
                message = error.get("message") or ""
                return f"{message} [{code}]" if code else message
            if body.get("detail"):
                return str(body["detail"])[:300]
        return str(body)[:300]

    async def health(self):
        if not self.base_url:
            return False, "не задан base_url"
        try:
            async with httpx.AsyncClient(timeout=15, headers=self._headers()) as client:
                ready = await client.get(f"{self.base_url}/readyz")
                if ready.status_code not in (200, 503):
                    return False, f"HTTP {ready.status_code}: {self._error_text(ready)}"
                deps = ready.json().get("deps", {})
                nodes = deps.get("nodes", "узлы неизвестны")
                if ready.status_code == 503:
                    return False, f"шлюз не готов: {nodes}"

                models = await client.get(f"{self.base_url}/api/v1/models")
                if models.status_code == 401:
                    return False, "неверный или отсутствующий API-ключ"
                self._raise_for_error(models, "список моделей")
                spec = next((m for m in models.json()["models"] if m["id"] == self.model), None)
            if spec is None:
                return False, f"модель «{self.model}» не найдена в реестре шлюза"
            available = spec.get("available_on") or []
            if not available:
                return False, f"веса «{self.model}» не лежат ни на одном узле"
            return True, f"{nodes}, {self.model} на {', '.join(available)}"
        except Exception as exc:
            return False, str(exc)

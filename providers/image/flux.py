"""FLUX (Black Forest Labs) — flux-pro-1.1-ultra."""
import asyncio
import logging
import os

import httpx

from providers.image.base import ImageProvider, download_bytes

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bfl.ml/v1"


class FluxProvider(ImageProvider):
    type = "flux"
    PARAMS = [
        {"key": "width", "label": "Ширина", "kind": "int", "default": 1344, "min": 256, "max": 2048},
        {"key": "height", "label": "Высота", "kind": "int", "default": 768, "min": 256, "max": 2048},
        {"key": "steps", "label": "Шаги", "kind": "int", "default": 50, "min": 1, "max": 100},
    ]

    def describe(self):
        return self.config.get("endpoint", "flux-pro-1.1-ultra")

    def _headers(self):
        return {"x-key": os.getenv("BFL_API_KEY", ""), "Content-Type": "application/json"}

    async def generate(self, prompt, params):
        endpoint = self.config.get("endpoint", "flux-pro-1.1-ultra")
        payload = {"prompt": prompt, **self.apply_defaults(params)}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{BASE_URL}/{endpoint}",
                                         headers=self._headers(), json=payload)
            if response.status_code != 200:
                raise RuntimeError(f"«{self.name}»: FLUX API {response.status_code}: "
                                   f"{response.text[:300]}")
            request_id = response.json()["id"]
            logger.info("«%s»: запрос %s создан", self.name, request_id)

            for attempt in range(60):
                await asyncio.sleep(5)
                poll = await client.get(f"{BASE_URL}/get_result",
                                        headers=self._headers(), params={"id": request_id})
                poll.raise_for_status()
                result = poll.json()
                status = result.get("status")
                if status == "Ready":
                    return await download_bytes(result["result"]["sample"])
                if status not in ("Pending", "Processing"):
                    raise RuntimeError(f"«{self.name}»: статус FLUX «{status}»: "
                                       f"{str(result)[:200]}")
        raise TimeoutError(f"«{self.name}»: FLUX не ответил за 300 с")

    async def health(self):
        if not os.getenv("BFL_API_KEY"):
            return False, "нет BFL_API_KEY"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{BASE_URL}/get_result",
                                            headers=self._headers(),
                                            params={"id": "00000000-0000-0000-0000-000000000000"})
            if response.status_code < 500:
                return True, "API отвечает"
            return False, f"HTTP {response.status_code}"
        except Exception as exc:
            return False, str(exc)

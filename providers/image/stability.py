"""Stability AI — Stable Image Ultra (v2beta)."""
import logging
import os
import random

import httpx

from providers.image.base import ImageProvider

logger = logging.getLogger(__name__)

API_URL = "https://api.stability.ai/v2beta/stable-image/generate/ultra"
BALANCE_URL = "https://api.stability.ai/v1/user/balance"


class StabilityProvider(ImageProvider):
    type = "stability"
    PARAMS = [
        {"key": "aspect_ratio", "label": "Соотношение сторон", "kind": "choice",
         "choices": ["16:9", "1:1", "21:9", "2:3", "3:2", "4:5", "5:4", "9:16", "9:21"],
         "default": "16:9"},
        {"key": "negative_prompt", "label": "Негативный промпт", "kind": "str",
         "default": "low quality, watermark"},
        {"key": "output_format", "label": "Формат", "kind": "choice",
         "choices": ["png", "jpeg", "webp"], "default": "png"},
    ]

    def describe(self):
        return "Stable Image Ultra"

    @staticmethod
    def _headers():
        return {"Authorization": f"Bearer {os.getenv('STABILITY_API_KEY', '')}",
                "Accept": "image/*"}

    async def generate(self, prompt, params):
        values = self.apply_defaults(params)
        fields = {
            "prompt": (None, prompt),
            "negative_prompt": (None, values.get("negative_prompt", "")),
            "aspect_ratio": (None, values.get("aspect_ratio", "16:9")),
            "output_format": (None, values.get("output_format", "png")),
            "seed": (None, str(random.randint(0, 4294967294))),
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(API_URL, headers=self._headers(), files=fields)
        if response.status_code != 200:
            raise RuntimeError(f"«{self.name}»: Stability API {response.status_code}: "
                               f"{response.text[:300]}")
        return response.content

    async def health(self):
        if not os.getenv("STABILITY_API_KEY"):
            return False, "нет STABILITY_API_KEY"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(BALANCE_URL, headers={
                    "Authorization": f"Bearer {os.getenv('STABILITY_API_KEY')}"})
            if response.status_code == 200:
                return True, f"баланс: {response.json().get('credits', '?')} кредитов"
            return False, f"HTTP {response.status_code}"
        except Exception as exc:
            return False, str(exc)

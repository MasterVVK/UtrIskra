"""OpenAI Images API (DALL-E / gpt-image) — через SOCKS5-прокси."""
import base64
import logging
import os

import httpx
from httpx_socks import AsyncProxyTransport

from providers.image.base import ImageProvider

logger = logging.getLogger(__name__)

API_URL = "https://api.openai.com/v1/images/generations"


class DalleProvider(ImageProvider):
    type = "dalle"
    PARAMS = [
        {"key": "model", "label": "Модель", "kind": "str", "default": "gpt-image-2"},
        {"key": "size", "label": "Размер", "kind": "str", "default": "1536x1024"},
        {"key": "quality", "label": "Качество", "kind": "str", "default": "auto"},
    ]

    def describe(self):
        return "OpenAI Images"

    def _client(self):
        kwargs = {"timeout": httpx.Timeout(float(self.config.get("timeout", 300)))}
        proxy_url = os.getenv("PROXY_URL", "")
        if self.config.get("proxy", True) and proxy_url:
            kwargs["transport"] = AsyncProxyTransport.from_url(proxy_url)
        return httpx.AsyncClient(**kwargs)

    def _headers(self):
        return {"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}",
                "Content-Type": "application/json"}

    async def generate(self, prompt, params):
        values = self.apply_defaults(params)
        payload = {"model": values.get("model", "gpt-image-2"), "prompt": prompt,
                   "size": values.get("size", "1536x1024"),
                   "quality": values.get("quality", "auto"), "n": 1}
        async with self._client() as client:
            response = await client.post(API_URL, headers=self._headers(), json=payload)
            if response.status_code != 200:
                raise RuntimeError(f"«{self.name}»: OpenAI API {response.status_code}: "
                                   f"{response.text[:300]}")
            item = response.json()["data"][0]
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"])
            if item.get("url"):
                download = await client.get(item["url"])
                download.raise_for_status()
                return download.content
        raise RuntimeError(f"«{self.name}»: в ответе нет ни b64_json, ни url")

    async def health(self):
        if not os.getenv("OPENAI_API_KEY"):
            return False, "нет OPENAI_API_KEY"
        try:
            async with self._client() as client:
                response = await client.get("https://api.openai.com/v1/models",
                                            headers=self._headers())
            return (True, "API доступен") if response.status_code == 200 \
                else (False, f"HTTP {response.status_code}")
        except Exception as exc:
            return False, str(exc)

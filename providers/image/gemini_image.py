"""Gemini Image — генерация через SDK google-genai с ротацией ключей.

Переписан относительно services/gemini_image_service.py: при исчерпании
ключей поднимает RuntimeError, а не sys.exit(1) (критично внутри веб-сервиса).
"""
import logging
import os

import httpx

from providers.image.base import ImageProvider

logger = logging.getLogger(__name__)


class GeminiImageProvider(ImageProvider):
    type = "gemini_image"
    PARAMS = [
        {"key": "model", "label": "Модель", "kind": "str", "default": "gemini-2.5-flash-image"},
    ]

    def _keys(self):
        keys_env = self.config.get("keys_env", "GEMINI_API_KEYS")
        return [k.strip() for k in os.getenv(keys_env, "").split(",") if k.strip()]

    def describe(self):
        return "google-genai SDK"

    async def generate(self, prompt, params):
        from google import genai
        from google.genai import types

        values = self.apply_defaults(params)
        model = values.get("model", "gemini-2.5-flash-image")
        keys = self._keys()
        if not keys:
            raise RuntimeError(f"«{self.name}»: нет ключей GEMINI_API_KEYS")
        last_error = None
        for index, api_key in enumerate(keys, 1):
            try:
                client = genai.Client(api_key=api_key)
                stream = client.models.generate_content_stream(
                    model=model,
                    contents=[prompt],
                    config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
                )
                for chunk in stream:
                    if chunk.candidates and chunk.candidates[0].content \
                            and chunk.candidates[0].content.parts:
                        part = chunk.candidates[0].content.parts[0]
                        if part.inline_data and part.inline_data.data:
                            return part.inline_data.data
                raise ValueError("в потоке ответа нет данных изображения")
            except Exception as exc:
                last_error = exc
                logger.warning("«%s»: ключ #%d не сработал: %s", self.name, index, exc)
        raise RuntimeError(f"«{self.name}»: все ключи ({len(keys)}) не сработали, "
                           f"последняя ошибка: {last_error}")

    async def health(self):
        keys = self._keys()
        if not keys:
            return False, "нет ключей"
        model = next((p.get("default") for p in self.param_schema if p["key"] == "model"),
                     "gemini-2.5-flash-image")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}",
                    params={"key": keys[0]})
            if response.status_code == 200:
                return True, f"модель {model} доступна, ключей: {len(keys)}"
            return False, f"HTTP {response.status_code}"
        except Exception as exc:
            return False, str(exc)

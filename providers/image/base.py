"""Базовый интерфейс image-провайдера.

Каждый провайдер получает промпт и словарь параметров, возвращает bytes
готового изображения (скачивание URL / декодирование base64 — внутри).
`param_schema` описывает поддерживаемые параметры — по нему UI строит форму:
  {"key", "label", "kind": "int"|"float"|"str"|"bool"|"choice",
   "default", "min"?, "max"?, "choices"?}
"""
import os

import httpx


class ImageProvider:
    type = "base"
    PARAMS = []  # схема параметров типа; local_task берёт её из конфига инстанса

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config

    @property
    def param_schema(self) -> list:
        return self.config.get("params") or self.PARAMS

    def apply_defaults(self, params: dict) -> dict:
        """Дефолты схемы + переданные значения; неизвестные ключи отбрасываются."""
        result = {}
        for spec in self.param_schema:
            value = params.get(spec["key"], spec.get("default"))
            if value is None:
                continue
            result[spec["key"]] = _coerce(spec.get("kind", "str"), value)
        return result

    async def generate(self, prompt: str, params: dict) -> bytes:
        raise NotImplementedError

    async def health(self) -> tuple:
        """(ok: bool, сообщение) — проверка доступности без генерации."""
        return False, "проверка не реализована"

    def describe(self) -> str:
        return self.config.get("base_url", "") or self.config.get("model", "")


def _coerce(kind, value):
    try:
        if kind == "int":
            return int(value)
        if kind == "float":
            return float(value)
        if kind == "bool":
            return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on", "да")
    except (TypeError, ValueError):
        return value
    return value


async def download_bytes(url: str, timeout: float = 180, proxy: bool = False) -> bytes:
    """Скачивает файл; proxy=True — через SOCKS5 из PROXY_URL."""
    kwargs = {"timeout": timeout, "follow_redirects": True}
    proxy_url = os.getenv("PROXY_URL", "")
    if proxy and proxy_url:
        from httpx_socks import AsyncProxyTransport
        kwargs["transport"] = AsyncProxyTransport.from_url(proxy_url)
    async with httpx.AsyncClient(**kwargs) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def build_image_provider(name: str, config: dict) -> ImageProvider:
    """Фабрика по полю config["type"]."""
    from providers.image.local_task import LocalTaskProvider
    from providers.image.stability import StabilityProvider
    from providers.image.dalle import DalleProvider
    from providers.image.flux import FluxProvider
    from providers.image.kandinsky import KandinskyProvider
    from providers.image.yandex import YandexProvider
    from providers.image.gemini_image import GeminiImageProvider
    from providers.image.qwen_chat import QwenChatProvider

    types = {p.type: p for p in (LocalTaskProvider, StabilityProvider, DalleProvider,
                                 FluxProvider, KandinskyProvider, YandexProvider,
                                 GeminiImageProvider, QwenChatProvider)}
    provider_type = config.get("type")
    if provider_type not in types:
        raise ValueError(f"Неизвестный тип image-провайдера «{provider_type}» (инстанс {name})")
    return types[provider_type](name, config)

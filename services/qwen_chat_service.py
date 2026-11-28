import re
import httpx
import logging
from config import QWEN_CHAT_API_URL, QWEN_CHAT_API_KEY

logger = logging.getLogger(__name__)


class QwenChatService:
    """Асинхронный клиент Qwen2API (OpenAI-совместимая обёртка chat.qwen.ai)."""

    IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

    def __init__(
        self,
        base_url: str = QWEN_CHAT_API_URL,
        api_key: str = QWEN_CHAT_API_KEY,
        timeout: int = 900,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        model: str = "qwen3.7-plus-image",
        temperature: float = 0.7,
        top_p: float = 0.95,
    ) -> str:
        """
        Генерирует изображение через POST /v1/chat/completions.
        URL картинки приходит внутри markdown-блока ![image](URL) в content.
        :return: Абсолютный URL сгенерированного изображения.
        """
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "size": aspect_ratio,
            "stream": False,
            "temperature": temperature,
            "top_p": top_p,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            except httpx.RequestError as e:
                logger.error(f"Ошибка подключения к Qwen2API: {e}")
                raise
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Ошибка статуса HTTP: {e.response.status_code} - {e.response.text}"
                )
                raise

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"Неожиданный формат ответа Qwen2API: {data}") from e

        match = self.IMAGE_MARKDOWN_RE.search(content or "")
        if not match:
            raise RuntimeError(
                f"URL изображения не найден в ответе. Фрагмент content: {content[:300]!r}"
            )

        image_url = match.group(1).strip()
        logger.info(f"Получен URL изображения: {image_url}")
        return image_url

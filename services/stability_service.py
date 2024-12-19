import httpx
from config import STABILITY_API_KEY


class StabilityService:
    """Класс для генерации изображений через Stability.ai API."""

    API_URL = "https://api.stability.ai/v2beta/stable-image/generate/sd3"

    def __init__(self):
        self.headers = {"Authorization": f"Bearer {STABILITY_API_KEY}"}

    async def generate_image(self, prompt: str) -> bytes:
        """Генерация изображения по запросу."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                json={"prompt": prompt, "output_format": "png"},
                headers=self.headers
            )
            response.raise_for_status()
            return response.content

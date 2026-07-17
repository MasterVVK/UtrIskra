"""MidJourney (Kolersky API): imagine-задача → сетка 2×2 → кроп выбранной позиции.

Возвращает bytes вырезанного квадранта — дальше работает обычный image-пайплайн
(водяной знак, БД, публикация, debug-режим).
"""
import io
import logging
import os

from PIL import Image

from providers.image.base import ImageProvider, download_bytes

logger = logging.getLogger(__name__)


class MidjourneyProvider(ImageProvider):
    type = "midjourney"
    PARAMS = [
        {"key": "aspect_ratio", "label": "Соотношение сторон", "kind": "choice",
         "choices": ["1:1", "16:9", "9:16", "4:3", "3:4"], "default": "16:9"},
        {"key": "speed", "label": "Скорость (тариф)", "kind": "choice",
         "choices": ["relaxed", "fast", "turbo"], "default": "relaxed"},
        {"key": "crop_position", "label": "Позиция из сетки 2×2", "kind": "choice",
         "choices": ["1", "2", "3", "4"], "default": "1"},
    ]

    def describe(self):
        return "Kolersky MJ API"

    async def generate(self, prompt, params):
        from services.midjourney_service import MidjourneyService, extract_output
        values = self.apply_defaults(params)
        service = MidjourneyService()
        result = service.execute_with_retry(
            task_func=lambda: service.create_imagine_task(
                prompt, aspect_ratio=values.get("aspect_ratio", "16:9"),
                speed=values.get("speed", "relaxed")),
            task_name="text-to-image")
        grid_url = (extract_output(result).get("collage") or {}).get("image_url")
        if not grid_url:
            raise RuntimeError(f"«{self.name}»: нет URL сетки в ответе: {str(result)[:300]}")
        grid_bytes = await download_bytes(grid_url)
        return _crop_quadrant(grid_bytes, int(values.get("crop_position", 1)))

    async def health(self):
        if not os.getenv("MIDJOURNEY_API_TOKEN"):
            return False, "нет MIDJOURNEY_API_TOKEN"
        return True, "токен задан (без запроса к API)"


def _crop_quadrant(image_bytes: bytes, position: int) -> bytes:
    """Вырезает квадрант из сетки 2×2 (1 — верхний левый … 4 — нижний правый)."""
    image = Image.open(io.BytesIO(image_bytes))
    width, height = image.size
    half_w, half_h = width // 2, height // 2
    boxes = {
        1: (0, 0, half_w, half_h),
        2: (half_w, 0, width, half_h),
        3: (0, half_h, half_w, height),
        4: (half_w, half_h, width, height),
    }
    if position not in boxes:
        raise ValueError(f"Позиция кропа должна быть 1–4, получено: {position}")
    output = io.BytesIO()
    image.crop(boxes[position]).save(output, format="PNG")
    return output.getvalue()

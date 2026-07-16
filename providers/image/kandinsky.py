"""Kandinsky (FusionBrain) — обёртка существующего services/kandinsky_service.py."""
import base64
import logging

from providers.image.base import ImageProvider

logger = logging.getLogger(__name__)

PROMPT_LIMIT = 1000  # лимит Kandinsky API


class KandinskyProvider(ImageProvider):
    type = "kandinsky"
    PARAMS = [
        {"key": "width", "label": "Ширина", "kind": "int", "default": 1344, "min": 128, "max": 2048},
        {"key": "height", "label": "Высота", "kind": "int", "default": 768, "min": 128, "max": 2048},
    ]

    def describe(self):
        return "FusionBrain API"

    async def generate(self, prompt, params):
        from services.kandinsky_service import KandinskyService
        values = self.apply_defaults(params)
        if len(prompt) > PROMPT_LIMIT:
            logger.warning("«%s»: промпт обрезан до %d символов", self.name, PROMPT_LIMIT)
            prompt = prompt[:PROMPT_LIMIT]
        service = KandinskyService()
        model_id = service.get_model_id()
        service.check_availability_with_timeout(model_id)
        uuid = service.generate_image(prompt, model_id,
                                      width=values.get("width", 1344),
                                      height=values.get("height", 768))
        image_base64 = service.get_image(uuid)
        return base64.b64decode(image_base64)

    async def health(self):
        try:
            from services.kandinsky_service import KandinskyService
            model_id = KandinskyService().get_model_id()
            return True, f"pipeline id: {model_id}"
        except Exception as exc:
            return False, str(exc)

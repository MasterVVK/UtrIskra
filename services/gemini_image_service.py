
import httpx
from httpx_socks import SyncProxyTransport
from config import GEMINI_API_KEYS, PROXY_URL
import sys
import base64

class GeminiImageService:
    """
    Класс для взаимодействия с API генерации изображений Gemini.
    Предполагается, что API похоже на другие сервисы Gemini.
    """

    def __init__(self, timeout: int = 120):
        if not GEMINI_API_KEYS:
            raise ValueError("GEMINI_API_KEYS отсутствуют. Проверьте файл config.py.")
        if not PROXY_URL:
            raise ValueError("PROXY_URL отсутствует. Проверьте файл config.py.")
        
        self.api_keys = GEMINI_API_KEYS
        self.current_key_index = 0
        self.proxy_url = PROXY_URL
        
        self.transport = SyncProxyTransport.from_url(self.proxy_url)
        self.client = httpx.Client(transport=self.transport, timeout=httpx.Timeout(timeout))

    @property
    def current_key(self) -> str:
        return self.api_keys[self.current_key_index]

    def switch_to_next_key(self):
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        print(f"[INFO] Переключение на следующий ключ: {self.current_key}")

    def generate_image(self, prompt: str) -> bytes:
        """
        Генерирует изображение на основе текстового промпта.
        """
        # ПРЕДПОЛОЖЕНИЕ: Мы предполагаем, что эндпоинт для генерации изображений
        # имеет следующий формат. Это может потребовать корректировки.
        api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateImage"

        for _ in range(len(self.api_keys)):
            try:
                response = self.client.post(
                    api_url,
                    params={"key": self.current_key},
                    headers={"Content-Type": "application/json"},
                    json={
                        "prompt": {
                            "text": prompt
                        }
                    },
                )

                if response.status_code == 200:
                    # ПРЕДПОЛОЖЕНИЕ: Мы предполагаем, что ответ содержит
                    # изображение в формате base64 в поле 'image_data'.
                    image_data = response.json().get("image_data")
                    if image_data:
                        return base64.b64decode(image_data)
                    else:
                        raise ValueError("Ответ API не содержит данных изображения.")
                elif response.status_code == 429:
                    print(f"[WARNING] Ключ {self.current_key} исчерпан. Переключаемся.")
                    self.switch_to_next_key()
                    continue
                else:
                    print(f"[ERROR] Ошибка API {response.status_code}: {response.text}")
                    # В случае другой ошибки, переключаемся на следующий ключ
                    self.switch_to_next_key()
                    continue

            except Exception as e:
                print(f"[ERROR] Ошибка при запросе к Gemini Image API: {e}")
                self.switch_to_next_key()
                continue
        
        print("[CRITICAL] Все API-ключи недействительны или исчерпаны. Завершение работы.")
        sys.exit(1)


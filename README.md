# UtrIskra

**UtrIskra** — система ежедневной генерации и публикации AI-изображений в Telegram.
Веб-панель управляет задачами генерации: расписание, промпты с версионированием,
выбор LLM- и image-провайдеров, debug-публикация, галерея и логи.

Поддерживаемые генераторы: Stability AI, MidJourney (Kolersky), DALL-E / gpt-image,
Flux (BFL), Kandinsky (FusionBrain), Yandex Art, Gemini Image, Qwen Chat и любые
self-hosted серверы с task-API (Qwen-Image, Z-Image, ERNIE, HiDream, …).
Промпты генерируются цепочкой LLM (Gemini → OpenAI-совместимый fallback:
Ollama / vLLM / Qwen2API и т.п.).

---

## Архитектура

```
webapp/      FastAPI-панель: дашборд, галерея, история, запуски, логи,
             настройки задач и провайдеров, встроенный APScheduler
core/        пайплайны (image / midjourney_video / best_image_video),
             задачи (jobs.json), промпты (SQLite, версии), публикация
providers/   адаптеры LLM и генераторов изображений (единый интерфейс)
services/    низкоуровневые обёртки API (midjourney, kandinsky, yandex, qwen_chat)
utils/       SQLite, водяной знак, логирование
storage/     runtime: изображения, база, конфиги панели (вне git)
```

Пайплайн `image`: промпт из БД (+плейсхолдеры) → цепочка LLM → image-провайдер →
водяной знак → SQLite → Telegram. Видео-пайплайны: MidJourney кадр → публикация →
image-to-video; best-of — самое популярное фото группы по реакциям (Telethon) →
CDN → видео.

Подробности: [docs/webapp.md](docs/webapp.md),
[docs/architecture-providers.md](docs/architecture-providers.md).

---

## Установка

1. Клонируйте репозиторий и установите зависимости:
   ```bash
   git clone https://github.com/MasterVVK/UtrIskra.git
   cd UtrIskra
   python -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```

2. Создайте `.env` (ключи — по используемым провайдерам):
   ```env
   TELEGRAM_TOKEN=токен_бота
   TARGET_CHAT_ID=id_канала
   DEBUG_TELEGRAM_TOKEN=токен_отладочного_бота   # опционально, для debug-режима
   DEBUG_TARGET_CHAT_ID=id_отладочного_чата
   GEMINI_API_KEYS=ключ1,ключ2
   PROXY_URL=socks5://...                        # прокси для Gemini
   BASE_STORAGE_PATH=/абсолютный/путь/к/storage
   FONTS_PATH=/абсолютный/путь/к/fonts
   STABILITY_API_KEY=... MIDJOURNEY_API_TOKEN=... OPENAI_API_KEY=...
   BFL_API_KEY=... KANDINSKY_API_KEY=... KANDINSKY_SECRET_KEY=...
   YANDEX_API_KEY=... FOLDER_ID=...
   TELETHON_API_ID=... TELETHON_API_HASH=... TELETHON_PEER=...   # для best-of
   ```

3. Запустите панель:
   ```bash
   python run_web.py                # http://хост:8090
   ```
   Для продакшена — systemd-юнит `deploy/utriskra-web.service`.

---

## Использование

- **Веб-панель** — основная точка управления: включение расписаний, ручной
  запуск с живым логом, редактирование промптов (версии в БД), настройка
  провайдеров, архив задач, debug-публикация в отдельный чат.
- **CLI**: `python -m core.run <ключ задачи>` (ключи — в `storage/webapp/jobs.json`).
- **Best-of** требует разовой авторизации Telethon:
  `python -m core.telethon_login`.

## База данных (`storage/database/daily_images.db`)

- `daily_images`: id, date, system_prompt, user_prompt, generated_prompt, image_path
- `job_prompts`: версии промптов задач (последняя — актуальная)

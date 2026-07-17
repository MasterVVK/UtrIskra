# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## О проекте

**UtrIskra** - система автоматической генерации и публикации AI-изображений в Telegram через различные генераторы (Stability AI, Flux, DALL-E, MidJourney, Kandinsky, Yandex Art, Gemini Image). Использует Gemini Pro для генерации промптов и APScheduler для планирования публикаций.

## Midjourney API - Прямая загрузка изображений

API поддерживает endpoint `/v1/midjourney/image/upload` для прямой загрузки изображений через base64 без использования внешних сервисов.

**Метод `upload_image()` в MidjourneyService** (`services/midjourney_service.py:32-72`):
- Конвертирует локальный файл в base64
- Загружает на CDN Kolersky через POST запрос
- Возвращает публичный URL вида `https://cdn.kolersky.com/uuid/image.png`
- Поддерживаемые форматы: PNG, JPG/JPEG, WebP
- Максимальный размер: 100MB
- Автоматическое удаление через 15 дней
- Бесплатная операция (не расходует requests)

**Преимущества**:
- Безопасность: токен бота не передается на сторонние ресурсы (catbox.moe, tmpfiles.org и т.п.)
- Нативная интеграция с Midjourney API
- Надежность: изображения хранятся на CDN провайдера

## Основные команды

### Установка зависимостей
```bash
pip install -r requirements.txt
```

### Веб-приложение (панель управления)
```bash
python run_web.py                      # вручную, порт 8090 (WEB_HOST/WEB_PORT в .env)
sudo systemctl restart utriskra-web    # прод: systemd-сервис
journalctl -u utriskra-web -f          # логи сервиса
```
Пакет `webapp/` — FastAPI-панель: встроенный APScheduler (расписание редактируется в UI, хранится в `storage/webapp/schedule.json`), ручной запуск, галерея, история, логи запусков (`storage/webapp/runs.jsonl`), журнал приложения (`storage/webapp/app.log`, страница «Логи»), настройки задач (включая промпты) и провайдеров.

Генерация построена на модульной архитектуре (см. `docs/architecture-providers.md`):
- **задачи** — `storage/webapp/jobs.json`, исполняются пайплайном `core/pipeline.py` (промпт из БД с плейсхолдерами → цепочка LLM → image-провайдер → водяной знак → SQLite → Telegram); CLI: `python -m core.run <ключ>`;
- **промпты** — в SQLite, таблица `job_prompts` (`core/prompts.py`): привязаны к задаче, каждое изменение — новая версия; редактируются на странице настроек задачи;
- **провайдеры** — `providers/llm/*` (gemini, openai-совместимые: Ollama/vLLM/Qwen2API) и `providers/image/*` (`local_task` покрывает все self-hosted task-API одним классом; `midjourney` — imagine + кроп сетки), инстансы в `storage/webapp/providers.json`;
- **видео-пайплайны** — `midjourney_video` (кадр → публикация → image-to-video) и `best_image_video` (популярное фото группы по реакциям через Telethon → CDN → видео).

Подробности: `docs/webapp.md`.

### Инициализация базы данных
```bash
python utils/database.py
```

### Запуск отдельной задачи из терминала
```bash
python -m core.run <ключ задачи>    # ключи: storage/webapp/jobs.json (например hidream, qwen, midjourney)
```

## Архитектура

### Основной поток работы (пайплайн `image`)
1. **APScheduler внутри веб-панели** запускает задачу по расписанию (или вручную из UI)
2. **Промпт задачи** читается из SQLite (`job_prompts`), плейсхолдеры рендерятся, текст генерируется цепочкой LLM-провайдеров (fallback настраивается)
3. **Image-провайдер** создаёт изображение (bytes) через соответствующий API
4. Изображение сохраняется в `storage/images/{year}/{month}/{filename}.png`, накладывается водяной знак
5. Метаданные записываются в SQLite (`storage/database/daily_images.db`)
6. Публикация в Telegram через `core/publisher.py` (ретраи, debug-режим, caption)

### Структура модулей

**config.py**: Централизованная конфигурация через .env переменные. Все API ключи и пути загружаются здесь.

**core/**: пайплайны (`pipeline.py`), задачи (`jobs.py`), промпты (`prompts.py`), провайдеры-конфиги (`providers_store.py`), публикация (`publisher.py`), runtime-настройки (`app_settings.py`), CLI (`run.py`)

**providers/**: адаптеры LLM (`llm/`: gemini с ротацией ключей и прокси, openai-совместимые) и генераторов изображений (`image/`: local_task, stability, dalle, flux, kandinsky, yandex, gemini_image, qwen_chat, midjourney)

**services/**: низкоуровневые обёртки API, используемые провайдерами: `midjourney_service.py` (Kolersky: imagine/video/upload на CDN), `kandinsky_service.py`, `yandex_service.py`, `qwen_chat_service.py`

**webapp/**: FastAPI-панель (маршруты, планировщик, менеджер запусков с логами, реестр задач, шаблоны, статика)

**utils/**: `database.py` (SQLite: daily_images), `image_utils.py` (водяной знак), `logger.py`

## Конфигурация (.env)

Обязательные переменные:
- `GEMINI_API_KEYS` - список ключей через запятую для ротации
- `PROXY_URL` - SOCKS5 прокси для доступа к Gemini API
- `TELETHON_API_ID`, `TELETHON_API_HASH` - Telegram API credentials для Telethon (получить на https://my.telegram.org/auth)
- `TELETHON_PEER` - ID группы для анализа реакций (задача best_image_video, `core/pipeline.py`)
- `TELEGRAM_TOKEN` - токен Telegram бота
- `TARGET_CHAT_ID` - ID чата/канала для публикации
- `DEBUG_TELEGRAM_TOKEN`, `DEBUG_TARGET_CHAT_ID` - (опционально) отладочный бот и чат для debug-режима публикаций (тумблер на дашборде панели или флаг у задачи)
- `BASE_STORAGE_PATH` - корневая директория для хранения (обычно "storage")
- `FONTS_PATH` - путь к шрифтам для водяных знаков на изображениях

API ключи генераторов (по необходимости):
- `STABILITY_API_KEY`, `BFL_API_KEY`, `OPENAI_API_KEY`, `MIDJOURNEY_API_TOKEN`, `KANDINSKY_API_KEY`, `KANDINSKY_SECRET_KEY`, `OAUTH_TOKEN` (Yandex), `FOLDER_ID` (Yandex)

## База данных

SQLite схема (`daily_images`):
- `id` - автоинкремент
- `date` - дата создания (YYYY-MM-DD)
- `system_prompt` - системный промпт для Gemini
- `user_prompt` - пользовательский промпт
- `generated_prompt` - финальный промпт для генератора изображений
- `image_path` - путь к сохраненному файлу

## Расписание публикаций

Управляется из веб-панели (дашборд: тумблер + время у каждой задачи), хранится в `storage/webapp/schedule.json`. По умолчанию всё выключено.

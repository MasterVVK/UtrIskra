# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## О проекте

**UtrIskra** - система автоматической генерации и публикации AI-изображений в Telegram через различные генераторы (Stability AI, Flux, DALL-E, MidJourney, Kandinsky, Yandex Art, Gemini Image). Использует Gemini Pro для генерации промптов и APScheduler для планирования публикаций.

## Основные команды

### Установка зависимостей
```bash
pip install -r requirements.txt
```

### Запуск планировщика
```bash
python main.py
```
Запускает основной планировщик с автоматической публикацией историй по расписанию (каждый день в разное время для разных генераторов).

### Инициализация базы данных
```bash
python utils/database.py
```

### Запуск отдельных генераторов (для тестирования)
```bash
python bot/daily_runner.py          # Stability AI (7:00)
python bot/kandinsky_runner.py      # Kandinsky (8:00)
python bot/midjourney_runner.py     # MidJourney (9:00)
python bot/dalle_runner.py          # DALL-E (10:00)
python bot/flux_runner.py           # Flux (11:00)
python bot/yandex_runner.py         # Yandex Art (12:00)
python bot/gemini_image_runner.py   # Gemini Image (13:00)
```

### Тестирование доступности сервисов
```bash
python services/test_availability.py
```

## Архитектура

### Основной поток работы
1. **Планировщик** (`bot/scheduler.py`) запускает раннеры по расписанию через APScheduler
2. **Раннер** (например `bot/daily_runner.py`) генерирует промпт через Gemini Pro
3. **Сервис генерации** (например `services/stability_service.py`) создает изображение
4. Изображение сохраняется в структуру `storage/images/{year}/{month}/{filename}.png`
5. Метаданные записываются в SQLite (`storage/database/daily_images.db`)
6. Изображение отправляется в Telegram через Aiogram

### Структура модулей

**config.py**: Централизованная конфигурация через .env переменные. Все API ключи и пути загружаются здесь.

**services/**: Сервисы для работы с AI API
- `gemini_service.py` - генерация текстовых промптов с ротацией API ключей и обработкой 503/429 ошибок
- `stability_service.py` - Stability AI через REST API
- `flux_service.py`, `dalle_service.py`, `midjourney_service.py`, `kandinsky_service.py`, `yandex_service.py` - другие генераторы изображений
- `gemini_image_service.py` - генерация изображений через Gemini Image API

**bot/**: Раннеры и планировщик
- Каждый раннер (`*_runner.py`) - независимый модуль генерации и публикации
- `scheduler.py` - настройка cron-задач для автоматической публикации

**utils/**:
- `database.py` - работа с SQLite (схема: id, date, system_prompt, user_prompt, generated_prompt, image_path)
- `logger.py` - настройка логирования
- `image_utils.py` - обработка изображений
- `prompt_utils.py` - утилиты для работы с промптами

### Ключевые особенности реализации

**Ротация API ключей**: `gemini_service.py` реализует автоматическое переключение между GEMINI_API_KEYS при ошибках 429 (quota exceeded) или 400 (invalid key). При 503 делает 3 попытки с задержкой 50 секунд.

**Прокси**: Все запросы к Gemini идут через SOCKS5 прокси (`PROXY_URL`), настроенный через `httpx-socks`.

**Структура хранения**: Изображения организованы по годам и месяцам для удобной навигации и архивирования.

**Telegram интеграция**: Используется Aiogram для отправки изображений. TARGET_CHAT_ID определяет целевой чат/канал.

**Динамические промпты**: В `daily_runner.py:67-87` реализована система выбора темы на основе дня месяца (день % 10), что обеспечивает разнообразие контента.

## Конфигурация (.env)

Обязательные переменные:
- `GEMINI_API_KEYS` - список ключей через запятую для ротации
- `PROXY_URL` - SOCKS5 прокси для доступа к Gemini API
- `TELEGRAM_TOKEN` - токен Telegram бота
- `TARGET_CHAT_ID` - ID чата/канала для публикации
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

Определено в `bot/scheduler.py:22-28`:
- 07:00 - Stability AI
- 08:00 - Kandinsky
- 09:00 - MidJourney
- 10:00 - DALL-E
- 11:00 - Flux
- 12:00 - Yandex Art
- 13:00 - Gemini Image

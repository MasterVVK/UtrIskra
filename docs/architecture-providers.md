# Архитектура: провайдеры и задачи

> **Статус: внедрено** (2026-07-16). Отклонения от исходного дизайна:
> 1) расписание осталось в `storage/webapp/schedule.json` (runtime-состояние,
> управляемое с дашборда), а `jobs.json` описывает состав задач — так меньше
> связность; 2) промпты хранятся не в файлах, а в SQLite (таблица
> `job_prompts`, `core/prompts.py`): привязаны к задаче, версия на каждое
> изменение, редактирование — на странице настроек задачи; `prompt_file`
> в jobs.json остался как источник разовой миграции. Спец-пайплайны
> (MidJourney-кроп, видео, best-of) пока работают через `pipeline: "legacy"`
> — вызов старых раннеров без изменений.

*Цель: модульность под личный проект — ежедневная генерация картинок в свою
группу через разные модели (платные облачные и self-hosted), со сменой
провайдеров и параметров из настроек панели, без правки кода.*

## Принципы

1. **Провайдер** — адаптер с единым интерфейсом. Два вида: LLM (текст промпта)
   и Image (картинка). Инстансы провайдеров описываются конфигом — один класс
   может обслуживать несколько инстансов (разные URL/модели).
2. **Задача (job)** — единица расписания: «промпт-файл + LLM + генератор +
   оформление + публикация». Задачи — это **данные** (JSON), а не файлы кода.
   Новая задача/вторая публикация в день = ещё одна запись в конфиге.
3. **Секреты остаются в `.env`** — конфиги ссылаются на имена переменных
   (`api_key_env`), а не на значения. Конфиги можно безопасно показывать в UI.
4. Личный проект: минимум абстракций — два базовых класса, один пайплайн,
   плоские JSON-конфиги. Без DI-контейнеров, плагинов и реестров-магии.

## 1. LLM-провайдеры

```python
# providers/llm/base.py
class LLMProvider:
    type: str                      # "gemini" | "openai"
    def __init__(self, name: str, config: dict): ...
    def generate(self, system_prompt: str, user_prompt: str,
                 *, temperature: float = 0.7, max_tokens: int = 8000) -> str: ...
    def health(self) -> tuple[bool, str]: ...   # для страницы «Здоровье» и кнопки «тест»
```

Двух реализаций достаточно надолго:

- **`gemini`** — перенос логики из `GeminiService`: ротация `GEMINI_API_KEYS`,
  503-ретраи, SOCKS5-прокси (опционально), но **модель — из конфига**;
  `print` → `logging` (диагностика попадает в логи запусков панели).
- **`openai`** — любой OpenAI-совместимый endpoint (`/chat/completions`).
  Покрывает всё self-hosted: Qwen2API, Ollama, vLLM, LM Studio, llama.cpp-server,
  а также OpenRouter/OpenAI при желании. Конфиг: `base_url`, `model`,
  `api_key_env`, `timeout`.

Инстансы — в `storage/webapp/providers.json`:

```json
{
  "llm": {
    "gemini":    {"type": "gemini", "model": "gemini-3.5-flash", "keys_env": "GEMINI_API_KEYS", "proxy": true},
    "qwen-max":  {"type": "openai", "base_url": "http://192.168.0.58:3001/v1", "model": "qwen3.7-max-thinking", "api_key_env": "QWEN_CHAT_API_KEY"},
    "ollama":    {"type": "openai", "base_url": "http://192.168.0.60:11434/v1", "model": "qwen3.5:32b"}
  },
  "llm_chain": ["gemini", "qwen-max"]
}
```

**Цепочка fallback — настройка, а не хардкод** (сейчас fallback зашит внутрь
`GeminiService`). Пайплайн идёт по цепочке; пустой ответ провайдера считается
ошибкой (сейчас пустая строка молча уходит в генератор картинок). Задача может
переопределить провайдера/цепочку и температуру.

## 2. Image-провайдеры

```python
# providers/image/base.py
class ImageProvider:
    type: str
    param_schema: list[dict]   # описание параметров для автоформы в UI:
                               # {key, label, kind: int|float|str|bool|choice, default, min, max, choices}
    async def generate(self, prompt: str, params: dict) -> bytes: ...
    async def health(self) -> tuple[bool, str]: ...
```

**Всегда возвращают `bytes`** — скачивание URL / декодирование base64 внутри
адаптера. Пайплайн един и не знает про форматы ответов.

Типы адаптеров (оборачивают существующие `services/*`, код сервисов на первом
этапе не переписывается):

| type | Покрывает | Примечание |
|---|---|---|
| `local_task` | **qwen, zimage, ernie, hidream — одним классом** | у всех идентичный API (`POST /api/v1/generate` → поллинг `GET /api/v1/tasks/{id}` + `/health`); отличия (cfg_scale vs guidance_scale, use_pe, model) описываются `param_schema` в конфиге инстанса. **Новый self-hosted генератор = запись в JSON, ноль кода** |
| `stability` | Stability Ultra | aspect_ratio, negative_prompt, output_format, seed — в параметры |
| `dalle` | OpenAI Images | model, size, quality |
| `flux` | BFL | width/height, steps |
| `kandinsky` | FusionBrain | width/height, лимит промпта |
| `yandex` | AliceAI Art | лимит промпта (size не отдавать в UI — API его игнорирует) |
| `gemini_image` | Gemini Image | `sys.exit(1)` заменить на исключение |
| `qwen_chat` | chat.qwen.ai (картинка из markdown) | model, size, top_p |
| `midjourney` | Kolersky MJ | + умения grid-кроп и video для спец-пайплайнов |

Конфиг инстансов:

```json
{
  "image": {
    "hidream": {"type": "local_task", "base_url": "http://192.168.0.60:8003",
                "params": [
                  {"key": "aspect_ratio", "kind": "choice", "choices": ["16:9","1:1","9:16"], "default": "16:9"},
                  {"key": "use_pe", "kind": "bool", "default": true}
                ]},
    "zimage":  {"type": "local_task", "base_url": "http://192.168.0.60:8001",
                "params": [
                  {"key": "model", "kind": "str", "default": "base"},
                  {"key": "num_inference_steps", "kind": "int", "default": 30, "min": 1, "max": 100},
                  {"key": "guidance_scale", "kind": "float", "default": 5.0, "min": 1, "max": 20}
                ]},
    "stability": {"type": "stability"},
    "dalle":     {"type": "dalle"}
  }
}
```

## 3. Задачи (jobs) вместо раннеров

11 из 15 раннеров — один и тот же код с разными данными. Эти данные и есть job:

```json
{
  "hidream_daily": {
    "title": "HiDream",
    "pipeline": "image",
    "prompt_file": "hidream_runner.txt",
    "llm": {"provider": "gemini", "temperature": 0.7, "max_theme": 50},
    "image": {"provider": "hidream", "params": {"aspect_ratio": "16:9", "use_pe": true}},
    "watermark": {"letter": "H", "enabled": true},
    "publish": {"chat_id": null, "retries": 3},
    "file_prefix": "hidream_story",
    "schedule": {"enabled": true, "hour": 19, "minute": 0}
  }
}
```

`storage/webapp/jobs.json`; текущий `schedule.json` вливается сюда.
Первичный конфиг генерируется автоматически из текущего реестра (все 15 задач
с сегодняшними параметрами — поведение не меняется).

**Пайплайны** (`core/pipeline.py`):

- `image` (11 задач): промпт-файл → LLM-цепочка → image-провайдер → водяной
  знак → БД → публикация;
- `midjourney_grid`: + кроп сетки 2×2 (позиция — параметр задачи);
- `midjourney_video`: изображение → видео (видео-промпт, motion — параметры задачи);
- `best_image_video`: Telethon-выборка по реакциям → видео (период — параметр;
  заодно чинится catbox→CDN Kolersky и запись в БД).

Что это даёт сразу:

- смена LLM или генератора у задачи — выпадающий список в UI;
- **несколько задач на один провайдер** (две публикации HiDream в день с разными
  промптами) — сейчас невозможно в принципе;
- новый self-hosted генератор — строчка конфига;
- dry-run и caption добавляются один раз в пайплайн, а не в 15 файлов.

## 4. Структура каталогов

```
providers/
├── llm/base.py, gemini.py, openai_compat.py
├── image/base.py, local_task.py, stability.py, dalle.py, flux.py,
│         kandinsky.py, yandex.py, gemini_image.py, qwen_chat.py, midjourney.py
core/
├── pipeline.py        # 4 типа пайплайна
├── jobs.py            # загрузка/валидация jobs.json
├── publisher.py       # Telegram-публикация (ретраи, chat_id, caption)
storage/webapp/
├── providers.json     # инстансы провайдеров (секреты — только имена env-переменных)
├── jobs.json          # задачи (расписание внутри)
```

`services/*` остаются — адаптеры их вызывают; втягивание кода в провайдеры —
по мере надобности. `runners/*` после перевода панели на пайплайн становятся
legacy (CLI-запуск заменяется `python -m core.run <job>`).

## 5. Изменения в панели

- **«Провайдеры»** — новая страница: две таблицы (LLM / изображения), статус
  health, кнопка «проверить», редактирование инстанса.
- **Карточка задачи → «Настройки»** — LLM (провайдер, температура), автоформа
  параметров по `param_schema`, знак, публикация; кнопка «Клонировать задачу».
- **Редактор промпт-файлов** — список, textarea, валидация маркеров, бэкап
  предыдущей версии.
- Дашборд/запуски/галерея — без изменений (ключи задач сохраняются).

## 6. Порядок внедрения

1. `providers/` + `core/` + автогенерация `providers.json`/`jobs.json` из
   текущих значений; панель переключается на пайплайн. Поведение 1:1.
2. UI: страница «Провайдеры» (+health), настройки задач, редактор промптов.
3. Спец-пайплайны: midjourney_grid / midjourney_video / best_image_video
   (с починкой найденных проблем).
4. Чистка: legacy-раннеры, `main.py`, `runners/scheduler.py`,
   `test_availability.py` (заменяется health-страницей).

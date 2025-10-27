# Midjourney API

Полный набор эндпоинтов для работы с Midjourney AI генерацией изображений и видео.

## 🎨 Generate - Генерация контента

Создание изображений или видео из текстовых описаний или изображений.

**Endpoint:** `POST /v1/midjourney/generate`

### Параметры запроса
```json
{
  "taskType": "text-to-image|image-to-image|style-reference|omni-reference|image-to-video|image-to-video-hd (обязательно)",
  "prompt": "string (обязательно для text-to-image, image-to-image, style-reference, omni-reference, image-to-video, image-to-video-hd)",
  "fileUrl": "string (обязательно для image-to-image, image-to-video, image-to-video-hd, если не используется fileUrls)",
  "fileUrls": ["string"] (обязательно для image-to-image, image-to-video, image-to-video-hd, если не используется fileUrl, 1-5 URLs)",
  "aspectRatio": "1:2|9:16|2:3|3:4|5:6|6:5|4:3|3:2|1:1|16:9|2:1 (опционально, по умолчанию: 1:1)",
  "speed": "relaxed|fast|turbo (опционально, по умолчанию: relaxed, не используется для image-to-video, image-to-video-hd, omni-reference)",
  "version": "7|6.1|6|5.2|5.1|niji6 (опционально, по умолчанию: 7)",
  "variety": "integer (0-100, шаг 5, опционально, по умолчанию: 10)",
  "stylization": "integer (0-1000, шаг 50, опционально, по умолчанию: 1)",
  "weirdness": "integer (0-3000, шаг 100, опционально, по умолчанию: 1)",
  "ow": "integer (1-1000, шаг 1, опционально, только для omni-reference, по умолчанию: 500)",
  "waterMark": "string (опционально)",
  "enableTranslation": "boolean (опционально, по умолчанию: false)",
  "callBackUrl": "string<uri> (опционально)",
  "videoBatchSize": "1|2|4 (опционально, только для image-to-video, image-to-video-hd, по умолчанию: 1)",
  "motion": "low|high (обязательно для image-to-video, image-to-video-hd, по умолчанию: high)"
}
```

### Примечания
- Используйте либо `fileUrl`, либо `fileUrls`, но не оба одновременно.
- Для `image-to-video` и `image-to-video-hd` `fileUrls` принимает только один URL.

### Ответ при приеме
```json
{
  "requestId": "uuid",
  "status": "accepted",
  "code": 200
}
```

### Финальный успешный ответ (для изображений)
```json
{
  "requestId": "uuid",
  "status": "success",
  "code": 200,
  "output": {
    "collage": {
      "image_url": "string",
      "actions": [
        { "index": 1, "requestId": "request_id_v1" }, // v1
        { "index": 2, "requestId": "request_id_v2" }, // v2
        { "index": 3, "requestId": "request_id_v3" }, // v3
        { "index": 4, "requestId": "request_id_v4" }, // v4
        { "index": 5, "requestId": "request_id_u1" }, // u1
        { "index": 6, "requestId": "request_id_u2" }, // u2
        { "index": 7, "requestId": "request_id_u3" }, // u3
        { "index": 8, "requestId": "request_id_u4" }  // u4
      ]
    }
  }
}
```

### Финальный успешный ответ (для видео)
```json
{
  "requestId": "uuid",
  "status": "success",
  "code": 200,
  "output": {
    "video_urls": [
      "https://cdn.kolersky.com/video/.../0_0.mp4",
      "https://cdn.kolersky.com/video/.../0_1.mp4"
    ],
    "actions": []
  }
}
```

### Пример использования
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/generate" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "taskType": "text-to-image",
    "prompt": "beautiful sunset over mountains with lake",
    "aspectRatio": "16:9",
    "speed": "relaxed",
    "version": "7",
    "variety": 10,
    "stylization": 1,
    "weirdness": 1,
    "waterMark": "my_watermark",
    "enableTranslation": false,
    "callBackUrl": "https://api.kolersky.com/callback"
  }'
```

---

## 🔄 Variation - Создание вариаций

Создание вариаций коллажа для выбранного изображения.

**Endpoint:** `POST /v1/midjourney/variation`

### Параметры запроса
```json
{
  "requestId": "string (обязательно)",
  "index": "1|2|3|4 (обязательно)",
  "waterMark": "string (опционально)",
  "callBackUrl": "string<uri> (опционально)"
}
```

### Пример использования
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/variation" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "request_12345",
    "index": 1,
    "waterMark": "my_watermark",
    "callBackUrl": "https://api.kolersky.com/callback"
  }'
```

---

## 📈 Upscale - Масштабирование

Увеличение разрешения выбранного изображения.

**Endpoint:** `POST /v1/midjourney/upscale`

### Параметры запроса
```json
{
  "requestId": "string (обязательно)",
  "index": "1|2|3|4 (обязательно)",
  "waterMark": "string (опционально)",
  "callBackUrl": "string<uri> (опционально)"
}
```

### Пример использования
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/upscale" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "request_12345",
    "index": 2,
    "waterMark": "my_watermark",
    "callBackUrl": "https://api.kolersky.com/callback"
  }'
```

---

## 🔄 Reroll - Перегенерация

Повторная генерация контента с теми же параметрами.

**Endpoint:** `POST /v1/midjourney/reroll`

### Параметры запроса
```json
{
  "requestId": "string (обязательно)"
}
```

### Пример использования
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/reroll" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "request_12345"
  }'
```

---

## 🎭 Inpaint - Редактирование региона

Изменение части изображения с использованием маски.

**Endpoint:** `POST /v1/midjourney/inpaint`

### Параметры запроса
```json
{
  "requestId": "string (обязательно)",
  "prompt": "string (опционально)",
  "mask": "string (base64, обязательно)"
}
```

### Пример использования
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/inpaint" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "request_12345",
    "mask": "...base64 string"
  }'
```

---

## 📐 Outpaint - Расширение холста

Расширение изображения за пределы исходного размера.

**Endpoint:** `POST /v1/midjourney/outpaint`

### Параметры запроса
```json
{
  "requestId": "string (обязательно)",
  "prompt": "string (опционально)",
  "zoom_ratio": "1|1.5|2|(1,2] (опционально)",
  "aspectRatio": "1:2|9:16|2:3|3:4|5:6|6:5|4:3|3:2|1:1|16:9|2:1 (опционально, по умолчанию: 1:1)"
}
```

### Пример использования
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/outpaint" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "request_12345",
    "zoom_ratio": "2",
    "prompt": "flying night city",
    "aspectRatio": "16:9"
  }'
```

---

## ↔️ Pan - Расширение в направлении

Расширение изображения в заданном направлении.

**Endpoint:** `POST /v1/midjourney/pan`

### Параметры запроса
```json
{
  "requestId": "string (обязательно)",
  "prompt": "string (обязательно)",
  "direction": "up|down|left|right (обязательно)"
}
```

### Пример использования
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/pan" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "request_12345",
    "direction": "down",
    "prompt": "flying city, night"
  }'
```

---

## 🌱 Seed - Получение начальной информации

Получение начальной информации о задаче.

**Endpoint:** `POST /v1/midjourney/seed`

### Параметры запроса
```json
{
  "requestId": "string (обязательно)"
}
```

### Пример использования
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/seed" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "request_12345"
  }'
```

---

## ❌ Cancel - Отмена задачи

Отмена задачи в статусе `accepted`.

**Endpoint:** `DELETE /v1/midjourney/cancel`

### Параметры запроса
```json
{
  "requestId": "string (обязательно)"
}
```

### Пример использования
```bash
curl -X DELETE "https://api.kolersky.com/v1/midjourney/cancel" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "request_12345"
  }'
```

---

## ⚠️ Общие замечания

### Асинхронная обработка
Все операции выполняются асинхронно:
1. Получаете `requestId` со статусом `accepted`.
2. Периодически проверяете статус через `/v1/status?requestId={id}`.
3. Получаете финальный результат при `status: "success"`.

### Стоимость операций
- **Generate (text-to-image, image-to-image, style-reference, omni-reference), Variation, Upscale, Inpaint, Outpaint, Pan, Seed**: 1 request.
- **Generate (image-to-video, image-to-video-hd)**: 15 requests.
- **Cancel, Status**: 0 requests.

### Ограничения
- Максимум 60 проверок статуса (интервал 5 секунд).
- Таймаут операции: 5 минут.
- Максимум 5 изображений для `image-to-image`.
- Изображения и видео хранятся 15 дней.

### Ошибки
```json
{
  "err": "Insufficient requests",
  "code": 403,
  "message": "You have 0 requests remaining"
}
```

```json
{
  "err": "Invalid parameters",
  "code": 400,
  "message": "prompt is required"
}
```
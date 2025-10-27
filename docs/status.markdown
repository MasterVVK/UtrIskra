# Status & Monitoring

Эндпоинты для проверки статуса операций и мониторинга системы.

## 📊 Status Check - Проверка статуса

Получение статуса выполнения асинхронных операций.

**Endpoint:** `GET /v1/status`

### Параметры запроса
- **requestId** (query parameter, обязательно): UUID запроса.

### Пример использования
```bash
curl "https://api.kolersky.com/v1/status?requestId=550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer your_api_key"
```

### Формат ответа
```json
{
  "requestId": "uuid",
  "status": "accepted|processing|success|error",
  "code": 200,
  "output": {
    "progress": "string (0-100%)",
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
    },
    "video_urls": ["string"],
    "failReason": "string (при error)"
  }
}
```

### Статусы операций
| Статус | Описание | Действия |
|--------|----------|----------|
| `accepted` | Запрос принят в обработку | Ждать и проверять повторно |
| `processing` | Операция выполняется | Продолжать проверку |
| `success` | Операция завершена успешно | Получить результат |
| `error` | Произошла ошибка | Проверить `failReason` |

---

## 📈 Usage Statistics - Статистика использования

Получение статистики использования API.

**Endpoint:** `GET /v1/usage`

### Ответ
```json
{
  "userId": "uuid",
  "period": {
    "start": "2024-01-01T00:00:00.000Z",
    "end": "2024-01-31T23:59:59.999Z"
  },
  "requests": {
    "total": 150,
    "successful": 145,
    "failed": 5,
    "byEndpoint": {
      "/v1/midjourney/generate": 50,
      "/v1/midjourney/variation": 30,
      "/v1/midjourney/upscale": 20
    }
  },
  "credits": {
    "used": 25,
    "remaining": 75
  },
  "limits": {
    "requestsPerDay": 100,
    "creditsPerMonth": 100
  }
}
```

---

## 📊 Usage Chart - График использования

Получение данных для построения графиков использования.

**Endpoint:** `GET /v1/usage/chart`

### Параметры
- **period** (query): `day|week|month|year`
- **metric** (query): `requests|credits|errors`

### Пример
```bash
curl "https://api.kolersky.com/v1/usage/chart?period=week&metric=requests" \
  -H "Authorization: Bearer your_api_key"
```

### Ответ
```json
{
  "period": "week",
  "metric": "requests",
  "data": [
    { "date": "2024-01-01", "value": 25 },
    { "date": "2024-01-02", "value": 30 },
    { "date": "2024-01-03", "value": 45 }
  ]
}
```

---

## 🏥 Health Check - Проверка здоровья

Проверка работоспособности сервиса.

**Endpoint:** `GET /health`

### Ответ
```json
{
  "status": "ok|warning|error",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "version": "1.0.0",
  "uptime": 86400000,
  "services": {
    "database": "ok",
    "redis": "ok",
    "external": "ok"
  }
}
```

---

## 🔄 Автоматическая проверка статуса

### JavaScript пример
```javascript
async function waitForCompletion(requestId: string, apiKey: string, maxAttempts = 60): Promise<any> {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const response = await fetch(`https://api.kolersky.com/v1/status?requestId=${requestId}`, {
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json'
      }
    });

    const result = await response.json();

    if (result.status === 'success') {
      return result.output;
    }

    if (result.status === 'error') {
      throw new Error(result.output?.failReason || 'Unknown error');
    }

    // Ждем 5 секунд
    await new Promise(resolve => setTimeout(resolve, 5000));
  }

  throw new Error('Operation timeout');
}
```

### Python пример
```python
import time
import requests

def wait_for_completion(request_id: str, api_key: str, max_attempts=60):
    url = "https://api.kolersky.com/v1/status"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    for attempt in range(max_attempts):
        response = requests.get(f"{url}?requestId={request_id}", headers=headers)
        result = response.json()

        if result['status'] == 'success':
            return result['output']

        if result['status'] == 'error':
            raise Exception(result['output'].get('failReason', 'Unknown error'))

        time.sleep(5)  # Ждем 5 секунд

    raise Exception('Operation timeout')
```

---

## ⚡ Оптимизация проверок статуса

### Интервалы проверки
- **Первые 30 секунд**: проверка каждые 2 секунды.
- **1-2 минуты**: проверка каждые 5 секунд.
- **2-5 минут**: проверка каждые 10 секунд.
- **После 5 минут**: проверка каждые 30 секунд.

### Exponential backoff
```javascript
function getCheckInterval(attempt: number): number {
  if (attempt < 15) return 2000;      // 0-30 сек: каждые 2 сек
  if (attempt < 24) return 5000;      // 30 сек-2 мин: каждые 5 сек
  if (attempt < 36) return 10000;     // 2-5 мин: каждые 10 сек
  return 30000;                       // После 5 мин: каждые 30 сек
}
```

### Обработка таймаутов
```javascript
const MAX_ATTEMPTS = 60;
const TIMEOUT_ERROR = 'Operation timed out after 5 minutes';

try {
  const result = await waitForCompletion(requestId, apiKey);
  console.log('Success:', result);
} catch (error) {
  if (error.message.includes('timeout')) {
    console.log('Operation is still processing, check later');
  } else {
    console.error('Error:', error.message);
  }
}
```

---

## 📊 Мониторинг и алерты

### Ключевые метрики
- **Response Time**: среднее время ответа API.
- **Success Rate**: процент успешных операций.
- **Queue Length**: количество операций в очереди.
- **Error Rate**: процент ошибок по типам.

### Рекомендуемые алерты
- Success rate < 95%.
- Average response time > 30 секунд.
- Queue length > 50 операций.
- Error rate > 5%.

### Логирование
Все операции логируются с уровнем детализации:
- **DEBUG**: технические детали для отладки.
- **INFO**: общая информация о выполнении.
- **WARN**: потенциальные проблемы.
- **ERROR**: ошибки выполнения.
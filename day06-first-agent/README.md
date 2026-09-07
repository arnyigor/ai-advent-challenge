# Day 6: Первый агент

Подробный план разработки, статусы и инструкция передачи работы находятся в
[`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md).

Простой контекстный агент принимает запрос в web-чате или CLI, сам вызывает
LLM через API и возвращает ответ. Интерфейсы не знают деталей провайдеров:
вся логика запроса, истории и fallback инкапсулирована в `ChatAgent`.

## Архитектура

```text
Web / CLI -> ChatAgent.ask() -> LLMProvider.generate() -> LLM API
                  |                    |
                  |                    +-- DeepSeek -> Gemini -> Wormsoft -> RouterAI
                  +-- история и fallback
```

DeepSeek — основной провайдер (лучше держит headless/скриптовые запросы, чем
Gemini под нагрузкой видеозаписи); Gemini, Wormsoft и RouterAI остаются
резервом в `ChatAgent`'ном fallback.

- `agent.py` — отдельная сущность агента, история диалога и fallback.
- `providers.py` — `ClientProvider` (общий путь retries/cancellation/model
  fallback из `tools/llm`) с двумя тонкими подклассами — `DeepSeekProvider` и
  `GeminiProvider` — плюс `OpenAICompatibleProvider` для Wormsoft/RouterAI.
- `web_server.py` — локальный HTTP API и раздача web-интерфейса.
- `day06_agent.py` — CLI, использующий того же агента.
- `web/` — интерфейс чата; API-ключи в браузер не передаются.

`GET /api/config` возвращает только безопасную публичную конфигурацию Agent
Box: температуру, лимиты, размер истории, названия политик и состояние judge.
Системный промпт, настройки подключения и секреты в ответ не попадают.

Web-чат и CLI показывают provider-reported токены текущего ответа и их сумму
за in-memory сессию. Если конкретный провайдер не прислал usage, интерфейс
явно выводит `токены: н/д`; очистка контекста также обнуляет счётчик сессии.

Кнопка «Стоп» / `ChatAgent.cancel()` отменяет активный запрос кооперативно:
отменённый вызов не коммитится в историю и не учитывается в usage сессии.
При отмене или любой ошибке ответа под сообщением появляется кнопка
«Повторить» — она пересылает тот же текст без повторного ввода.

В web-чате и CLI можно выбрать конкретный провайдер (вместо
fallback-цепочки целиком) и уровень reasoning на конкретный запрос —
`ChatAgent.ask(text, provider_id=..., thinking_level=...)`, не затрагивая
сохранённый конфиг агента.

Ответы ассистента рендерятся из markdown (bold/italic/код/списки/
заголовки) в безопасный HTML — весь текст экранируется до вставки, см.
[web/markdown.selfcheck.mjs](web/markdown.selfcheck.mjs).

## Настройка

Основной провайдер:

```powershell
$env:DEEPSEEK_API_KEY = "ваш-ключ"
```

Резервные провайдеры включаются автоматически, если заданы переменные:

```powershell
$env:GEMINI_API_KEY = "ваш-ключ"
$env:WORMSOFT_API_KEY = "ваш-ключ"
$env:WORMSOFT_BASE_URL = "OpenAI-compatible base URL из конфигурации провайдера"
$env:ROUTERAI_API_KEY = "ваш-ключ"
```

Секреты не хранятся в репозитории и не отправляются в браузер.

## Запуск

```powershell
pip install -r requirements.txt
python web_server.py
```

Открыть <http://127.0.0.1:8006/>.

CLI:

```powershell
python day06_agent.py "Ответь одним словом: привет"
python day06_agent.py
```

## Проверка

```powershell
python -m py_compile agent.py providers.py day06_agent.py web_server.py
python -m pytest tests/test_day6_agent.py tests/test_day6_providers.py tests/test_day6_web.py
node web/markdown.selfcheck.mjs
```

## Видео

Готовое демо: [`ChallengeVideos/day06-demo.mp4`](../ChallengeVideos/day06-demo.mp4).

Пересъёмка (headless Chrome CDP + ffmpeg, без npm-зависимостей):

```powershell
python web_server.py --port 0   # запомнить фактический порт из вывода
$env:DAY06_WEB_URL = "http://127.0.0.1:<port>/"
$env:DAY06_CDP_PORT = "9260"
node record-video.mjs
```

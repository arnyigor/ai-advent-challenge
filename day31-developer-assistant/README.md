# День 31. Ассистент разработчика

**Видео-демо:** [day31-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/vgJyd71QezoePA) — 0:55, 1920×1080, с русской озвучкой (QwenTTS Voice Design). Один вопрос `/help`: найденный фрагмент README/docs → короткий ответ Gemini со ссылкой на источник → текущая ветка `main`, прочитанная через MCP. Кадры — реальные снимки браузера, ожидание генерации сокращено и подписано; озвучка объясняет, что подтверждает каждый шаг. Локальная копия: `ChallengeVideos/day31-demo-voiced.mp4`, вне Git. Размер опубликованного файла совпал с локальным: 1 958 519 байт (md5 `3bacda8a426cf9e8d524853caccf1a7c`).

`/help` отвечает о **реальном AI Advent Challenge**: README и docs через RAG,
текущая ветка и HEAD через настоящий MCP stdio. CLI и браузер используют один
пайплайн; ответ показывает источники, Git-контекст и трассу MCP.

Подробный [план](PLAN.md), [сценарий демонстрации](DEMO.md), общая документация
в [docs](../docs/architecture.md), [контракт API](../docs/api.md),
[схема SQLite](../docs/data-model.md).

## Запуск из корня репозитория

**Локальная LLM не обязательна.** Можно использовать Gemini или бесплатный
OpenRouter. Embeddings и MCP остаются локальными; выбранные фрагменты документов
передаются указанному облачному провайдеру. Пример текущего запуска:

```powershell
$env:DAY31_LLM_PROVIDER = 'gemini'
$env:DAY31_LLM_MODEL = 'gemini-3.5-flash-lite'
# GEMINI_API_KEY задаётся в окружении, не в коде и не на видео.
$env:LOCAL_LLM_MAX_TOKENS = '700'
.\.venv\Scripts\python.exe day31-developer-assistant\server.py
```

Для бесплатного OpenRouter: DAY31_LLM_PROVIDER=openrouter,
DAY31_LLM_MODEL=openrouter/free, OPENROUTER_API_KEY в окружении. Допускаются только
openrouter/free или модели с суффиксом :free; платного fallback нет. Бесплатные
API могут возвращать 429; ошибка видна, модель не переключается скрытно.
DAY31_LLM_PROVIDER=local сохраняет первоначальный локальный режим.
У Gemini наличие free tier зависит от проекта/квоты, приложением биллинг не определяется.

Основное видео теперь — короткая версия с русской озвучкой QwenTTS Voice Design:
`ChallengeVideos/day31-demo-voiced.mp4`. Один вопрос демонстрирует README/docs,
ответ /help по источникам и текущую ветку через MCP. Подробности — DEMO.md.
Первая версия без озвучки сохранена как расширенное техническое видео.

Python 3.12+, Git, зависимости requirements.txt; локальный кеш
`intfloat/multilingual-e5-small`. Для первого скачивания кеша используйте свой
обычный процесс установки моделей: приложение работает с local_files_only.
Также нужны соседние папки дней 21 и 28, поскольку их код переиспользуется.

```powershell
.\.venv\Scripts\python.exe -m pip install -r day31-developer-assistant\requirements.txt
.\.venv\Scripts\python.exe day31-developer-assistant\assistant.py --index
.\.venv\Scripts\python.exe day31-developer-assistant\assistant.py --inspect
# Реальный MCP + semantic retrieval, без генерации:
.\.venv\Scripts\python.exe day31-developer-assistant\assistant.py '/help' --retrieve-only

# Укажите адрес и alias своей запущенной локальной модели:
$env:LOCAL_LLM_URL = 'http://127.0.0.1:8085/v1'
$env:LOCAL_LLM_MODEL = 'day31-qwen3.8-27b'
$env:LOCAL_LLM_MAX_TOKENS = '1024'
.\.venv\Scripts\python.exe day31-developer-assistant\assistant.py '/help Как устроен проект?'
.\.venv\Scripts\python.exe day31-developer-assistant\server.py
```

Откройте http://127.0.0.1:8796. Порт меняется через DAY31_WEB_PORT.
Индексирование не запускает LLM; старт UI не загружает E5 и не вызывает LLM.
При изменении README/docs выполнить `--index` снова. В UI выбранные фрагменты
раскрываются, MCP показывает настоящий каталог и результат инструмента.

## Корпус и поиск

Корневой README, README всех dayNN-* и Markdown из docs/. Скрытые папки,
секреты, исходники, evidence и видео не индексируются. Разбиение по секциям,
1000 символов; E5 CPU, SQLite vectors + FTS5, top-6. Проверяется SHA-256 корпуса
при каждом запросе. Индекс создаётся локально в data/ и исключён из Git.
Вопросы без номера дня ищут в общей docs, корневом README и README дня 31.
Укажите `day28` или «дня 28», чтобы добавить документацию нужного дня в поиск:
это предотвращает смешивание контрактов разных учебных приложений.

MCP-сервер day31-project предоставляет только get_project_context без аргументов.
Он выполняет фиксированные read-only git branch/rev-parse. Корень MCP совпадает
с корнем индексируемого проекта. Ветка читается заново на каждый вопрос.

## Проверка и ограничения

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_day31_assistant.py -q
.\.venv\Scripts\python.exe day31-developer-assistant\verify.py
```

Нет истории диалога, записи файлов, diff и списка файлов MCP. Ссылки [n]
проверяются по диапазону, но смысловая точность требует сверки по фрагментам.
Отказ на неизвестный факт обеспечивает инструкция модели; отдельного
семантического валидатора нет. Обрезанный ответ отмечается finish_reason=length.
Ошибки модели и MCP не подменяются успешными ответами. Маленькая локальная модель
может ошибаться; отчёт реального прогона приведён ниже.

Запуск собственного llama-server, если модель ещё не работает:

```powershell
# Задайте пути к установленному llama-server и скачанному GGUF.
powershell -ExecutionPolicy Bypass -File day31-developer-assistant\run-model.ps1 -LlamaServer $env:LLAMA_SERVER -ModelFile $env:DAY31_MODEL_FILE
```

Скрипт создаёт отдельный loopback-процесс на DAY31_MODEL_PORT (8085), alias
DAY31_MODEL_ALIAS (day31-qwen3.8-27b), окно 8192, один слот. Использованный GGUF:
Qwen3.8-27B-UD-Q3_K_XL, параметр --gpu-layers=99; для CPU задайте DAY31_GPU_LAYERS=0.
Модель и llama-server не входят в репозиторий. Другие процессы не останавливаются.

## Реальные результаты, 12 октября 2026

20 тестов дня 31, 5 тестов провайдеров моделей (Gemini/OpenRouter) и 14
регрессионных тестов дня 28 — 39 всего. Проверены настоящий MCP stdio,
смена ветки и detached HEAD во временном репозитории, устаревание индекса,
ограничения HTTP и отсутствие смешивания API разных дней.

Прогон CLI: 5 вопросов через E5 + MCP + Qwen3.8-27B, все 10 автоматических
критериев выполнены. Ещё 4 запроса сделаны через реальный headless Chrome и UI.
Ответы о структуре и API сверены с показанными источниками; ветка main совпала
с Git. На неизвестные бизнес-показатели получены отказы из-за отсутствия данных.
Все ответы завершились finish_reason=stop. Это небольшая приёмочная выборка,
а не доказательство правильности произвольных ответов.

Первая попытка с Qwen3-1.7B давала лишние отказы и смешивала API дня 24 с днём 31.
Она сохранена в evidence/pilot-qwen1.7b.json. После этого ограничена область
retrieval и добавлен отдельный system prompt помощника; более сильная модель
проверена уже с этими изменениями. Это не чистое сравнение двух моделей.

Доказательства: [CLI](evidence/acceptance.json), [браузер](evidence/browser-demo.json),
[короткий браузерный прогон](evidence/short-browser-demo.json), оригинальные снимки
ui-*.png и short-*.png в evidence/. Основное видео — короткий монтаж настоящих
снимков UI с русской озвучкой: 0:55, 1920×1080, H.264 + AAC, 25 fps. Ожидание
ответа сокращено и подписано. Первая длинная версия без озвучки (2:36) сохранена
как расширенное техническое видео в `ChallengeVideos/day31-demo.mp4`.

Видео (вне Git): опубликованное `ChallengeVideos/day31-demo-voiced.mp4`
и первая версия `ChallengeVideos/day31-demo.mp4`. Автоматическая запись по шагам
из [DEMO.md](DEMO.md): `node day31-developer-assistant/capture-demo.mjs`
(с `DAY31_SHORT_DEMO=1`), `python day31-developer-assistant/generate_narration.py
--submit`, `python day31-developer-assistant/record_short_video.py`; для длинной
версии — `python day31-developer-assistant/record_video.py`. Озвучка синтезируется
через API установленного ComfyUI с ComfyUI-QwenTTS, проверка произнесённого
текста — `verify_narration.py` (Python из ComfyUI, локальный Whisper). Нужны
Chrome, Node 22+, Pillow и ffmpeg; пути переопределяются переменными среды.
Видео не публикуется автоматически.

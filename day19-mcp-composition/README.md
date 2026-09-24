# День 19. Композиция MCP-инструментов

**Видео-демо:** [day19-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/A2PEbrR45JCm_g) — один запуск трёх MCP-методов, передача данных между ними, реальный ответ `gemini-3.5-flash` и сохранение TXT.

Один локальный MCP-сервер объявляет `search`, `summarize` и `saveToFile`. Клиент открывает одну stdio-сессию и автоматически вызывает все три метода. Данные из `search` передаются в `summarize`, а его сводка — в `saveToFile`. Источник — небольшой встроенный корпус о днях 16–18. Если доступен `GEMINI_API_KEY`, `summarize` вызывает **Gemini 3.5 Flash** (переопределение: `DAY19_MODEL`, одна из моделей `GEMINI_MODELS` дня 18). В ответе инструмента, интерфейсе и TXT указан фактически использованный режим и модель. Если ключа нет или вызов не удался, результат честно отмечен как локальная сводка без модели. VPS не нужен.

## Запуск

Из корня проекта, Python 3.11+:

```powershell
python -m pip install -r day19-mcp-composition/requirements.txt
python day19-mcp-composition/pipeline.py
python day19-mcp-composition/web_server.py
```

Последняя команда напечатает локальный URL. В браузере достаточно нажать **«Запустить цепочку»**. Страница показывает каталог инструментов, аргументы и результаты каждого реального `tools/call`, путь и содержимое сохранённого TXT. Для другого запроса: `python day19-mcp-composition/pipeline.py "RSS" --json`.

Файлы сохраняются в `day19-mcp-composition/output/`. Для отдельного каталога задайте `DAY19_OUTPUT_DIR`. Имя генерируется по `run_id`; произвольный путь клиенту не доступен. Для гарантированного запуска без модели задайте `DAY19_SUMMARY_MODE=plain`.

## Проверка и видео

```powershell
python -m pytest tests/test_day19_mcp_composition.py -q
python -m py_compile day19-mcp-composition/mcp_server.py day19-mcp-composition/pipeline.py day19-mcp-composition/web_server.py
node --check day19-mcp-composition/web/app.js
node day19-mcp-composition/record-video.mjs
```

Запись требует Node.js 22+, Chrome и ffmpeg. Результат: [day19-demo.mp4](../ChallengeVideos/day19-demo.mp4). Видео показывает один запуск и все три MCP-вызова. Для путей к программам доступны `PYTHON_PATH`, `CHROME_PATH`, `FFMPEG_PATH`.

План: [PLAN.md](PLAN.md).

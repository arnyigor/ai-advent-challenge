# День 20. Orchestration MCP

**Видео-демо:** [day20-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/YhqgwWGiIFNtpA) — живой запуск Gemini 3.5 Flash: ввод запроса, выбор инструментов трёх MCP-серверов и сохранённый отчёт.

Продолжение [дня 19](../day19-mcp-composition/README.md): Gemini 3.5 Flash самостоятельно выбирает инструменты трёх MCP-серверов и следующий шаг после каждого ответа. Видео хранится локально и исключено из Git.

## Запуск

Нужен `GEMINI_API_KEY`, как в дне 19. Из корня проекта:

```powershell
python -m pip install -r day20-mcp-orchestration/requirements.txt
python day20-mcp-orchestration/orchestrator.py
python day20-mcp-orchestration/web_server.py
```

Последняя команда печатает локальный URL. Откройте его, введите `MCP` и нажмите «Запустить агента». Для другого сценария: `python day20-mcp-orchestration/orchestrator.py "MCP без сохранения" --json`. Модель задаётся через `DAY20_MODEL`; по умолчанию `gemini-3.5-flash`. При отсутствии ключа запуск завершается с понятной ошибкой, без имитации выбора моделью.

## Что происходит

`servers.json` регистрирует три процесса stdio. Каждый проходит `initialize` и `tools/list`. Клиент превращает полученные схемы в объявления функций Gemini и хранит соответствие полного имени с MCP-сессией. Gemini возвращает имя инструмента и аргументы; клиент проверяет их по схеме, выполняет `tools/call`, возвращает результат модели и повторяет цикл. История сохраняет исходные части ответа Gemini, включая подписи рассуждения. Маршрутизатор не позволяет сохранить отчёт до успешной проверки.

| Сервер | Инструменты | Задача |
|---|---|---|
| knowledge | search, read | Искать и читать локальные материалы дней 16–18 |
| analysis | summarize, verify | Составить сводку из источников и проверить её |
| storage | save, read | Записать TXT и прочитать его обратно |

`knowledge.read` и `storage.read` направляются в разные процессы. На проверенном живом запросе `MCP` модель `gemini-3.5-flash` сделала 9 ходов и выбрала 8 вызовов: `search → read × 3 → summarize → verify → save → read`. Результат `storage.read` совпал с переданной сводкой. Это наблюдение одного запуска, а не жёстко заданный порядок в коде; модель может выбрать другой допустимый путь. Сводку формирует локальный инструмент `analysis.summarize`, Gemini решает, когда его вызвать.

Отчёты создаются в `output/` или каталоге `DAY20_OUTPUT_DIR`. Веб-сервер слушает только localhost и выбирает свободный порт, либо `DAY20_WEB_PORT`. Лимиты: 16 MCP-вызовов и 600 секунд на полный запуск.

## Проверка

```powershell
python -m pytest tests/test_day20_mcp_orchestration.py -q
python -m py_compile day20-mcp-orchestration/server.py day20-mcp-orchestration/gemini_agent.py day20-mcp-orchestration/orchestrator.py day20-mcp-orchestration/web_server.py
node --check day20-mcp-orchestration/web/app.js
node --check day20-mcp-orchestration/record-video.mjs
node day20-mcp-orchestration/record-video.mjs
```

Автоматические тесты используют модель-имитатор, которая принимает решения по полученным MCP-ответам, и запускают реальные MCP-процессы. Отдельно выполнен живой запуск Gemini. Запись требует Node.js 22+, Chrome и ffmpeg; пути можно задать через `PYTHON_PATH`, `CHROME_PATH`, `FFMPEG_PATH`.

[План и контракт](PLAN.md).

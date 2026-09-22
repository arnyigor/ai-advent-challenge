# День 17. Первый MCP-инструмент

**Видео-демо:** [day17-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/FUsxRxn2imiegA) — два реальных вызова MCP-инструмента из приложения, входная схема, результаты Git и ответы агента.

Свой MCP-сервер `git_mcp_server.py` оборачивает локальный Git и регистрирует `get_git_snapshot`. Параметр `scope` обязателен: `summary` читает ветку и число изменённых отслеживаемых файлов; `latest_commit` читает хеш, заголовок, автора и дату последнего коммита. Сервер не изменяет репозиторий.

`git_agent.py` запускает сервер по stdio, выполняет `initialize`, получает описание инструмента через `tools/list`, вызывает его через `tools/call` и формирует ответ из полученного результата. Агент детерминированный: это позволяет запустить демонстрацию без API-ключа. Веб-приложение использует тот же код агента.

## Запуск

Python 3.11+, Git в `PATH`. Из корня репозитория:

```powershell
python -m pip install -r day17-first-mcp-tool/requirements.txt
python day17-first-mcp-tool/web_server.py
```

Откройте адрес из консоли. Порт выбирается автоматически. Выберите вопрос и нажмите «Спросить агента». Интерфейс показывает объявленную сервером схему, аргументы `tools/call`, сырой результат и ответ агента.

CLI:

```powershell
python day17-first-mcp-tool/git_agent.py
python day17-first-mcp-tool/git_agent.py latest_commit --json
```

По умолчанию читается Git-репозиторий проекта. Для другого локального репозитория задайте `DAY17_REPO_ROOT` перед запуском. Веб-запрос принимает только один из двух сценариев и не принимает путь или команду Git.

## Проверка

```powershell
python -m pytest tests/test_day17_mcp_tool.py -q
python -m py_compile day17-first-mcp-tool/git_mcp_server.py day17-first-mcp-tool/git_agent.py day17-first-mcp-tool/web_server.py
node --check day17-first-mcp-tool/web/app.js
node --check day17-first-mcp-tool/record-video.mjs
```

Тесты запускают реальный дочерний MCP-процесс и проверяют оба сценария вызова, JSON Schema, использование ответа в тексте агента и веб-API. Проверка перед сдачей: `python -m pytest tests -q` — **288 passed**.

## Видео

[Локальный файл ChallengeVideos/day17-demo.mp4](../ChallengeVideos/day17-demo.mp4), 29,8 с. Для перезаписи: `node day17-first-mcp-tool/record-video.mjs`. Нужны Node.js 22+, Chrome и ffmpeg. Допускаются `PYTHON_PATH`, `CHROME_PATH`, `FFMPEG_PATH`. Кадры сохраняются в игнорируемом `video-frames/`.

План: [PLAN.md](PLAN.md). Сценарий: [VIDEO_SCRIPT.md](VIDEO_SCRIPT.md).

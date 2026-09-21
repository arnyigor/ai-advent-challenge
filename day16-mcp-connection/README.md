# День 16. Подключение MCP

**Видео-демо:** [day16-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/1MsrK6XwBPMpRg) — подключение учебного MCP и вашего Jarvis через UI предыдущих дней, получение 31 инструмента, поиск по каталогу, просмотр параметров и журнал соединения.

## Интерфейс на основе дня 15

```powershell
cd day16-mcp-connection
python -m pip install -r requirements.txt
python web_server.py
```

Откройте адрес, напечатанный сервером. Порт выбирается автоматически.
В корневом окружении проекта можно запускать из корня:

```powershell
.\.venv\Scripts\python.exe day16-mcp-connection/web_server.py
```

1. Выберите **Jarvis** или **Учебный сервер** и нажмите **Подключиться**.
2. Проверьте имя ответившего сервера и число инструментов.
3. Найдите инструмент через поиск и выберите его в списке.
4. Справа появятся описание, типы параметров и отметки обязательности.
5. Исходная JSON-схема раскрывается отдельно; ниже расположен журнал подключения.

Получение каталога завершается закрытием MCP-сессии. UI явно показывает это:
каталог остаётся доступен как снимок; **Обновить каталог** создаёт новое соединение.
При смене сервера старый результат очищается. Вызов инструментов не выполняется.

По умолчанию Jarvis ищется в соседнем с репозиторием каталоге `MCPs/McpServer`.
Если сервер находится в другом месте, задайте `JARVIS_MCP_ROOT` перед запуском.
Используется собственный `.venv` Jarvis. Если он не найден, профиль недоступен,
но учебный пример работает. API принимает только идентификатор настроенного профиля.

Оформление (палитра, панели, этапы) и HTTP-подход взяты из дня 15.
Веб-сервер вызывает существующую `discover()` из `mcp_client.py`.

Python-клиент подключается к MCP-серверу, выполняет `initialize` и `tools/list`,
выводит названия, описания и JSON Schema инструментов, затем закрывает сессию.
Инструменты не вызываются. LLM и API-ключи для локального примера не нужны.

## Отдельный CLI

Python 3.11+; команды из папки `day16-mcp-connection`:

```powershell
python -m pip install -r requirements.txt
python mcp_client.py
```

Клиент автоматически запускает `demo_server.py` тем же Python и соединяется
с ним по stdio. В выводе: `MCP handshake: OK`, сервер `day16-demo`,
`Available tools: 2`, инструменты `add` и `greet` с описаниями и схемами.
В `requirements.txt` закреплён официальный SDK `mcp==2.2.0`.

## Подключение к существующему MCP

```powershell
# Любая команда запуска stdio MCP; --command ставится последним.
python mcp_client.py --timeout 60 --command <путь-к-python-сервера> <путь-к-server.py>

# Получить весь каталог в машиночитаемом виде.
python mcp_client.py --json --command <программа> <аргументы>

# Streamable HTTP endpoint без авторизации.
python mcp_client.py --url http://localhost:8000/mcp
```

`--server <script.py>` запускает другой Python-сервер интерпретатором клиента.
Для сервера со своим окружением используйте `--command` и его Python.
Клиент обрабатывает страницы `tools/list`, если сервер возвращает `nextCursor`.
Таймаут по умолчанию — 30 секунд; ошибки завершают CLI с кодом 1.
HTTP-авторизация/OAuth в минимальном примере не реализованы.

## Проверено на существующем сервере

21 сентября 2026 года клиент подключился к пользовательскому **Jarvis MCP Server**
из проекта `McpServer`: handshake успешен, получен **31 инструмент**, включая
`list_directory`, `read_file`, `execute_python_code`, `rag_search` и `rag_ask`.
Каталог получен через реальное stdio-соединение с `server.py` в окружении сервера.
Это основной сценарий видео. Маленький `demo_server.py` оставлен для запуска
на другой машине и воспроизводимых интеграционных тестов.

## Проверка

Из корня репозитория, в окружении с установленным SDK:

```powershell
python -m pip install pytest
python -m py_compile day16-mcp-connection/mcp_client.py day16-mcp-connection/demo_server.py
python -m pytest tests/test_day16_mcp_connection.py -q
python -m pytest tests/test_day16_web.py -q
python -m py_compile day16-mcp-connection/web_server.py
node --check day16-mcp-connection/web/app.js
node --check day16-mcp-connection/record-ui.mjs
node --check day16-mcp-connection/record-video.mjs
```

Интеграционные тесты запускают реальные дочерние MCP-процессы: handshake,
названия и схемы инструментов, повторное подключение, обычный CLI,
отсутствующий сервер, выход до handshake и таймаут. Проверенный транспорт — stdio.
Проверено: **6 тестов CLI и 4 теста веб-API**; `py_compile` и `node --check` успешны.
Перед сдачей полный прогон `python -m pytest tests -q`: **283 passed**.
В браузере проверены Jarvis, учебный сервер, поиск, пустой результат,
смена сервера и отображение параметров. Журнал содержит реальные события клиента.

## Новое видео с интерфейсом

`../ChallengeVideos/day16-demo.mp4` — итоговая запись реальных действий в UI:
подключение учебного сервера, просмотр `add` и `greet`, подключение Jarvis,
поиск `list_directory`, просмотр параметров и JSON, пустой поиск,
просмотр `rag_search` и журнала.
Длительность — 1 минута 7 секунд. Контрольные кадры и полное декодирование MP4 проверены.

```powershell
node record-ui.mjs
```

Скрипт сам запускает веб-сервер и Chrome, проверяет результаты подключений
и записывает MP4: 1920×1080, H.264 Baseline, AAC, faststart.
Для сценария с Jarvis нужен доступный профиль (см. `JARVIS_MCP_ROOT`).
Нужны Node.js 22+, Chrome и ffmpeg. `PYTHON_PATH`, `CHROME_PATH`, `FFMPEG_PATH`
позволяют указать свои исполняемые файлы. Кадры в `video-frames/ui-*` исключены из git.

## Предыдущая техническая запись

При повторном запуске технического сценария результат сохраняется отдельно:
`../ChallengeVideos/day16-cli-demo.mp4`.
Длительность: 1 минута 42 секунды; 1440×1000, H.264.
Русские подписи; без озвучки. Скрипт показывает код, запускает настоящий CLI,
отображает результат `initialize`, весь каталог Jarvis, схему `list_directory`
и запускает pytest. Это запись отображения результатов реальных процессов.

Для повторной записи нужны Node.js 22+, Chrome, ffmpeg и pytest:

```powershell
# Без настройки — запись с небольшим сервером из этого дня.
node record-video.mjs

# Для записи со своим сервером задайте массив команды, не строку оболочки.
$env:MCP_DEMO_COMMAND = ConvertTo-Json -Compress -InputObject @(
  '<путь-к-python-сервера>', '<путь-к-server.py>'
)
node record-video.mjs
```

Скрипт выбирает Python из корневого `.venv`, если он существует; иначе `python`.
Переопределения: `PYTHON_PATH`, `CHROME_PATH`, `FFMPEG_PATH`.
Кадры и фактический JSON сохраняются в игнорируемой `video-frames/run-*`.
Видео исключено из git, как в предыдущих днях.

План: [PLAN.md](PLAN.md). Сценарий: [VIDEO_SCRIPT.md](VIDEO_SCRIPT.md).
Документация SDK: https://py.sdk.modelcontextprotocol.io/.

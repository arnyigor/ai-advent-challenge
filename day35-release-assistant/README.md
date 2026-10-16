# День 35 · AI Release Assistant

**Видео-демо:** [day35-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/nPoncA9xQkpg6g) — 1:38, реальный браузерный прогон: выбор версий DnsHostsGenerator → сбор Git-источников → JVM-тесты и Android/Windows-сборки → AI-анализ → просмотр diff и материалов обновления. Ожидание сборок/модели ускорено ×5 с подписью; без озвучки.

**Реальная задача:** подготовка обновлений собственного DnsHostsGenerator.
Сервис читает изменения между двумя версиями Git, собирает доказательства,
а AI пишет описание обновления, анализ рисков и ручной тест-план.

Результат используется как черновик материалов обновления v1.4.0 → v1.4.1.
Исходный проект: https://github.com/arnyigor/DnsHostsGenerator.
Предварительное исследование: [анализ и план](../docs/day35-analysis-plan.md).
Контракт до реализации: [CONTRACT.md](CONTRACT.md).

**Результат приёмки:** Gemini 3.8 Flash, 8 коммитов / 30 файлов / 32 источника,
полное покрытие. 19 тестов сервиса и 35 JVM-тестов DnsHostsGenerator прошли.
Собраны Android debug APK и Windows desktop с runtime; debug-подпись APK
проверена apksigner (v2). [Отчёт](evidence/report.html),
[описание обновления](evidence/release-notes.md), [тест-план](evidence/test-plan.md).
Локальная копия видео: `ChallengeVideos/day35-demo.mp4`, вне Git.
Файл опубликован на Яндекс.Диске: локальный и удалённый размер совпали —
1 722 753 байта. Перед сдачей полный набор Python: **498 passed**, одно
предупреждение Starlette/anyio; 19 Node-тестов также прошли.
Подробности публикации: [shipping.json](evidence/shipping.json).

## Запуск из корня AI Advent Challenge

Нужны Git и Node.js 22.13+ (проверено на 24.16). `npm install` не требуется.

```powershell
git clone https://github.com/arnyigor/DnsHostsGenerator.git day35-release-assistant/data/DnsHostsGenerator
$env:DAY35_MODEL = 'gemini-3.8-flash'
# GEMINI_API_KEY уже задан в окружении; не вставляйте ключ в терминал на видео.
node day35-release-assistant/server.mjs
```

Откройте http://127.0.0.1:8835. Если локальная копия уже существует, не запускайте
clone повторно. `DAY35_REPO` позволяет выбрать существующую копию DnsHostsGenerator.

Выберите base/head, провайдера и модель; нажмите «Подготовить материалы».
Провайдер по умолчанию Gemini, имя модели задаётся явно. При облачном провайдере
разрешённые фрагменты исходников передаются в облако; это показано до запуска.
Приложение не определяет доступный тариф/квоту Gemini.

```powershell
# CLI: без параметров выводит справку, без сетевых запросов.
node day35-release-assistant/cli.mjs
node day35-release-assistant/cli.mjs --collect-only
node day35-release-assistant/cli.mjs --base v1.4.0 --head v1.4.1

# Явный запуск проверок доверенного собственного проекта:
# JAVA_HOME и ANDROID_HOME/ANDROID_SDK_ROOT задаются под своё окружение.
node day35-release-assistant/cli.mjs --base v1.4.0 --head v1.4.1 --run-checks
```

Для локальной модели:

```powershell
$env:DAY35_PROVIDER = 'local'
$env:DAY35_MODEL = 'имя-вашей-модели'
$env:LOCAL_LLM_URL = 'http://127.0.0.1:8085/v1'
node day35-release-assistant/server.mjs
```

OpenRouter: `DAY35_PROVIDER=openrouter`, `OPENROUTER_API_KEY` в окружении,
модель `openrouter/free` или с суффиксом `:free`. Автопереключения между
моделями/провайдерами и платного fallback нет. Для HTTP 429/500/503 — до трёх
попыток на той же модели в рамках общего таймаута; попытки видны в трассе.

## Как AI участвует

Git collector фиксирует SHA, коммиты, diff, разрешённые документы и список
пропущенных/обрезанных источников. Модель получает эти факты и статусы проверок,
возвращает JSON с изменениями, рисками, ручными сценариями и описанием обновления.
Валидатор проверяет структуру и существование всех ссылок S. UI показывает
оригинальный diff для сверки каждого вывода. Команды модель не генерирует.

```text
CLI / браузер → общий runRelease → Git objects → evidence
                              → проверки точного SHA (по выбору)
                              → выбранная LLM → проверка JSON и ссылок
                              → Markdown + JSON + самостоятельный HTML
```

В `runs/<UUID>/` создаются evidence.json, analysis.json, trace.json,
release-notes.md, test-plan.md и report.html. При ошибке модели факты и отчёт
сохраняются; analysis.json отсутствует. Входной репозиторий не изменяется.
Локальные clones, результаты, логи и кадры исключены из Git.

## Фактические проверки и статусы

Профиль содержит `:shared:jvmTest`, `:androidApp:assembleDebug`,
`:desktopApp:createDistributable`. При явном выборе создаётся отдельный clone
выбранного SHA. Gradle запускается через Java wrapper без shell и получает
ограниченный набор переменных окружения. Ключи моделей не наследуются.
Gradle wrapper может скачивать Gradle, JDK toolchain и зависимости.
Логи находятся в `runs/<UUID>/logs/`. Таймаут завершает дерево процесса проверки.

- `blocked`: обязательная проверка failed/timeout.
- `incomplete`: не все проверки выполнены, AI недоступен, диапазон пуст,
  контекст неполный или SHA проверки не совпадает.
- `checks_passed_review_needed`: AI-анализ валиден, все обязательные проверки
  успешны для нужного SHA и контекст полный; требуется просмотр человеком.

Успешная Windows desktop-сборка не подтверждает Linux/macOS. Debug APK
не является production-публикацией. Подпись, устройство и магазин не проверяются.
Исходный workflow проекта уже выполняет матричную сборку по тегу; сервис
подготавливает материалы перед выпуском и не заменяет этот workflow.

## Настройки

`DAY35_REPO`, `DAY35_BASE`, `DAY35_HEAD`, `DAY35_PROVIDER`, `DAY35_MODEL`,
`DAY35_WEB_PORT` (8835), `DAY35_RUNS_DIR`, `DAY35_MAX_CONTEXT` (260000 символов),
`DAY35_CHECK_TIMEOUT_MS` (600000), `DAY35_MODEL_TIMEOUT_MS` (180000),
`DAY35_GRADLE_HOME` (по умолчанию изолированный кеш внутри checkout).
Local endpoint должен указывать на loopback. HTTP слушает только 127.0.0.1,
проверяет Host/Origin и не принимает произвольные пути или команды.

## Проверка и демонстрация

```powershell
node day35-release-assistant/verify.mjs
# Пересобрать переносимый пакет доказательств выбранного живого прогона:
node day35-release-assistant/verify-live.mjs 2d55af03-83ae-4673-9827-a122c0af8667
# При уже работающем сервере: новый живой AI-запрос и непрерывная запись.
node day35-release-assistant/capture-demo.mjs
```

Для видео нужны Chrome, ffmpeg и ffprobe. Пути: CHROME_PATH, FFMPEG_PATH,
FFPROBE_PATH; отдельный отладочный порт DAY35_CDP_PORT (9235).
Итог — `ChallengeVideos/day35-demo.mp4`, вне Git.
Только ожидание сборок/модели ускоряется с явной подписью. Для видео с проверками
задайте DAY35_DEMO_CHECKS=1. Сценарий: [DEMO.md](DEMO.md).
Сводка реальной приёмки и исходные материалы — [evidence](evidence/README.md).

## Ограничения

Проверка ID источников не доказывает смысловую точность текста AI.
Перед публикацией нужен просмотр описания и рискованных выводов.
Фильтрация путей/известных форматов ключей не является универсальным DLP.
Сборки исполняют код доверенного репозитория и могут обращаться в сеть.
Сервис не публикует релизы, не создаёт теги и не изменяет системный hosts.
RAG-индекс, MCP, автоматическое исправление кода и интеграция магазина
не нужны для реализованного сценария.

# Day 2: Response Control

## Что делает

Отправляет один и тот же содержательный запрос к Gemini API дважды и сравнивает результат:

- **A — baseline**: только исходный вопрос, без формата, без ограничения длины, без stop sequence.
- **B — controlled**: тот же вопрос + системная инструкция (`systemInstruction`) со строгим
  форматом ответа, лимитом слов и маркером конца ответа, а также `maxOutputTokens` и
  `stopSequences` на уровне API.

`thinkingConfig.thinkingLevel = low` одинаков для обоих запросов — A/B отличается только
механизмами контроля ответа (`systemInstruction`, `maxOutputTokens`, `stopSequences`).

Для controlled-ответа скрипт автоматически проверяет наличие всех секций формата, лимит слов
и отсутствие маркера конца ответа в возвращённом тексте, затем выводит итоговую таблицу
сравнения baseline vs controlled.

## Стек

- Python 3.10+
- requests — HTTP-запросы, без SDK
- Gemini REST `generateContent`, цепочка моделей 3.x (первичная `gemini-3.7-flash`;
  для видео-демо зафиксирована быстрая `gemini-3.5-flash-lite`)

## Установка

```bash
pip install -r requirements.txt
```

## Настройка ключа

Ключ берётся только из переменной окружения `GEMINI_API_KEY` (в коде и репозитории не хранится).
Подробная инструкция — в `tools/API_KEYS.md`.

## Запуск

Обычный демонстрационный режим (терминальный UI, интерактивные паузы Enter):

```bash
python day2_response_control.py
```

## Режимы и конфигурируемые ограничения

Ограничения (лимит слов, stop sequence, maxOutputTokens) не жёстко зашиты — задаются флагами:

```bash
python day2_response_control.py --mode text                      # по умолчанию, терминальный UI
python day2_response_control.py --mode json                      # один детерминированный JSON-документ, без пауз
python day2_response_control.py --no-interactive                 # text-режим без Enter-пауз (для записи/автоматизации)
python day2_response_control.py --word-limit 60 --stop-sequence "<STOP>" --max-output-tokens 200
python day2_response_control.py --model gemini-3.5-flash        # одна модель, без fallback
```

`--mode json` печатает **только** JSON в stdout (ничего больше) — схема ответа всегда одинаковая:
`model`, `model_chain`, `model_used`, `attempts`, `base_prompt`, `word_limit`, `stop_sequence`,
`max_output_tokens`, `error` (`null` при успехе), `results.baseline`, `results.controlled`
(включая `system_instruction` и `checks`), `comparison`. Набор полей не меняется ни от
содержимого ответов, ни от ошибок — при ошибке ответные поля заполняются пустыми значениями,
а текст ошибки попадает в `error` — удобно для скриптовой обработки.

### Fallback по моделям

Если модель недоступна (429 rate limit / 503 перегрузка после ретраев), **весь эксперимент**
(оба запроса целиком) переезжает на следующую модель в цепочке
`gemini-3.7-flash -> gemini-3.6-flash -> gemini-3.5-flash -> gemini-3.5-flash-lite -> gemini-3-flash-preview`
(по убыванию версий). Fallback на уровне эксперимента, а не отдельного запроса: baseline и
controlled всегда выполняются на **одной и той же** модели, иначе сравнение отражало бы
разницу моделей, а не контроль ответа.

- 429/503 → ретраи с паузой (2 попытки), затем следующая модель;
- 401/403 (плохой ключ) → сразу фатальная ошибка, без ретраев;
- `thinkingLevel=low` поддерживается всеми моделями цепочки, поэтому адаптация
  thinkingConfig при 400 не требуется;
- `--model <имя>` — зафиксировать одну модель и отключить fallback (для воспроизводимости);
- в JSON-выводе прозрачно видно, кто реально ответил: `model_used` + `attempts`.

## Видео

Публичная ссылка на демо-видео (`video/day2-demo.mp4`):

https://yadi.sk/i/_ShpeOV3GIvfuQ

## Запись видео-демо

Рабочий вариант — headless-рекордер (архитектура как у Day 1: фоновая «камера» + ffmpeg,
без видимого окна на экране, реальные вызовы Gemini API):

```bash
python record-video-headless.py
```

Итог: `video/day2-demo.mp4` — с субтитрами внизу кадра (фаза определяется по тексту
на экране: вопрос → запуск запросов → A → B → сравнение → итог). Требования: ffmpeg в PATH
(или `FFMPEG_PATH`), Pillow (`pip install pillow`), шрифт Consolas (стандартный для Windows;
переопределить `FONT_PATH`).

Альтернатива — запись реального видимого окна терминала (`record-video.ps1`, ffmpeg gdigrab
по заголовку окна). Работает **только** если запускать из своего обычного интерактивного
терминала на реальном рабочем столе — см. раздел «Диагностика» ниже.

```bash
powershell -ExecutionPolicy Bypass -File record-video.ps1
```

## Диагностика (что делать, если запись видео не работает)

Сначала прогони `check-day2.bat` (двойной клик или из терминала) — он сам проверит
python/ffmpeg/ключ/компиляцию и укажет, что именно не так.

### `record-video-headless.py`

| Симптом | Причина / решение |
|---|---|
| `GEMINI_API_KEY не задан в окружении` | ключ не установлен для текущего процесса — см. `tools/API_KEYS.md`, задать через `[Environment]::SetEnvironmentVariable(...)` и перезапустить терминал |
| `Consolas не найден` | нет `C:\Windows\Fonts\consola.ttf` — указать свой моноширинный шрифт через `FONT_PATH` |
| `ModuleNotFoundError: PIL` | не установлен Pillow — `pip install pillow` (только для рекордера, в `requirements.txt` основного скрипта не входит) |
| Видео пустое / все кадры чёрные | баг с блокирующим чтением stdout (`read(N)` ждёт N байт вместо доступных) — в текущей версии уже исправлено на `read1()`; если баг вернулся, искать в `reader()` |
| Видео обрывается почти сразу (~5-10 кадров) | скрипт упал с ошибкой сразу (например, невалидный ключ) — сама ошибка попадёт в кадр, смотри `video/frames/f0001.png` (или последний кадр) как картинку |
| Видео короче ожидаемого (~15-20 c) | это нормально: `gemini-3.5-flash-lite` с `thinkingLevel=low` отвечает быстро — интро + два live-запроса + финал укладываются в ~15-20 секунд |
| ffmpeg падает на сборке (`Error opening input`) | проверь, что кадры вообще создались: `ls video/frames`; если пусто — процесс завис на Enter-паузе (см. ниже) |
| Скрипт завис на "Press Enter to run..." | автосценарий рекордера ищет строки `"Press Enter to run"` / `"Press Enter to run comparison"` в выводе процесса — если тексты промптов в `day2_response_control.py` изменили, сценарий в `record-video-headless.py` (функция `main`, блок с `enter1_at`/`enter2_at`) нужно поправить под новые формулировки |
| Лишние процессы/файлы после сбоя | `video/frames/` не чистится автоматически после сборки mp4 — удалить вручную (`rm -rf video/frames`); зависшие процессы — `Stop-Process -Name python -Force` / `Stop-Process -Name ffmpeg -Force` (осторожно — может убить не тот процесс, если параллельно запущено что-то ещё) |

### `record-video.ps1` (запись реального окна)

| Симптом | Причина / решение |
|---|---|
| `Терминал window titled '...' did not appear within 10 seconds` | процесс не смог создать видимое окно на рабочем столе — типично для запуска из изолированной/удалённой/агентской сессии (сервис, SSH, CI, sandboxed-инструмент). Запустить скрипт нужно из **своего обычного** интерактивного PowerShell/терминала, а не из автоматизации |
| `ffmpeg`: `Invalid properties, aborting` / `capturing 0x0x32 at (0,0)` | целевое окно свёрнуто или имеет нулевой размер — окно должно быть развёрнуто и видимо на экране в момент старта записи |
| Кириллица в `.ps1` превращается в кракозябры при запуске | PowerShell 5.1 без BOM читает файл в системной кодировке — держать `.ps1`-скрипты в чистом ASCII (как сделано сейчас) или сохранять с UTF-8 BOM |
| Ключ не виден дочернему процессу | `GEMINI_API_KEY` должен быть задан на уровне пользователя (`[Environment]::SetEnvironmentVariable(..., "User")`), а не временной `$env:` в другом, уже закрытом терминале |

## Структура

```
day02-response-control/
├── day2_response_control.py    # основной скрипт (text/json режимы)
├── record-video-headless.py    # рабочий рекордер видео (без видимого окна)
├── record-video.ps1            # альтернативный рекордер (реальное окно, ffmpeg gdigrab)
├── check-day2.bat              # ручная проверка окружения перед запуском/записью
├── requirements.txt
├── video/day2-demo.mp4
└── README.md
```

> README будет дополнен после финальной проверки (commit hash, ссылка на выгруженное видео).

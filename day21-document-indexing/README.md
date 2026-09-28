# День 21. Индексация документов

🎥 **[Видео-демо: chunking → embeddings → SQLite → vector search](https://yadi.sk/i/V6nVAsg4jIcoiA)** — 29 секунд, 1920×1080.

Локальный pipeline индексирует документацию и Python-код дней 15–20 двумя
способами, генерирует multilingual embeddings и сохраняет два inspectable
SQLite-индекса. Веб-интерфейс показывает отличия чанков и результатов поиска.

## Быстрый запуск

Из корня репозитория:

```powershell
.\.venv\Scripts\python.exe -m pip install -r day21-document-indexing\requirements.txt
.\.venv\Scripts\python.exe day21-document-indexing\pipeline.py
.\.venv\Scripts\python.exe day21-document-indexing\compare.py
.\.venv\Scripts\python.exe day21-document-indexing\web_server.py
```

Сервер напечатает локальный адрес с автоматически выбранным портом. Также можно
запустить `run-web.bat` из папки дня.

Первый запуск скачивает `intfloat/multilingual-e5-small`. После загрузки модель
работает локально. Для smoke-проверки без сети доступен детерминированный backend:

```powershell
.\.venv\Scripts\python.exe day21-document-indexing\pipeline.py --model hash-384
.\.venv\Scripts\python.exe day21-document-indexing\compare.py --model hash-384
```

Hash backend предназначен для тестов; итоговое демо использует нейросетевую
модель и сохраняет её имя в каждой БД и отчёте.

## Корпус

Manifest выбирает README, планы, сценарии и Python-файлы дней 15–20, а также
наглядный документ `corpus/atlas-handbook.md`. Это 42 файла, 13 288 слов или около 26,6 страницы при
условном размере 500 слов на страницу.

PDF loader также поддерживается через PyMuPDF: каждая страница превращается в
Markdown-раздел `## Page N` и далее проходит тот же pipeline.

## Стратегии

### Fixed-size

Строгие окна по 1200 символов с overlap 200. Граница файла не пересекается,
но заголовки и границы функций не управляют разрезом.

### Structure-aware

Markdown делится по дереву заголовков, Python — по верхнеуровневым классам и
функциям через `ast`. Длинный раздел дополнительно режется на окна до 1200
символов с overlap 120.

## Результаты

После запуска появляются:

```text
data/indexes/fixed.sqlite3
data/indexes/structure.sqlite3
results/comparison.json
```

В каждом SQLite есть таблицы `index_runs`, `documents`, `chunks`,
`chunk_embeddings` и `chunk_fts`. Обязательные метаданные доступны напрямую в
`chunks`, полный JSON лежит в `metadata_json`, вектор — float32 BLOB.

Benchmark использует 13 вопросов и считает Hit@1, Hit@5 и MRR@5. Сравниваются
также число и размеры чанков, количество embeddings и размер БД.

### Фактический прогон

| Метрика | Fixed-size | Structure-aware |
|---|---:|---:|
| Чанков | 150 | 224 |
| Средний размер | 1054,6 | 634,6 |
| Median | 1200 | 533 |
| Hit@1 | 0.923 | 0.923 |
| Hit@5 | 1.000 | 1.000 |
| MRR@5 | 0.949 | **0.962** |
| Средний score релевантного результата | 0.8538 | **0.8611** |

Structure-aware индекс дал немного лучший порядок релевантных результатов, но
создал на 74 чанка больше и занял больше места. Полный воспроизводимый отчёт с
результатами каждого вопроса находится в `results/comparison.json`.

## Проверка

```powershell
$files = Get-ChildItem day21-document-indexing -Filter *.py -File
$files | ForEach-Object { .\.venv\Scripts\python.exe -m py_compile $_.FullName }
.\.venv\Scripts\python.exe -m pytest tests\test_day21_document_indexing.py -q
node --check day21-document-indexing\web\app.js
node --check day21-document-indexing\record-video.mjs
```

Видео создаётся командой `node record-video.mjs` и сохраняется как
`ChallengeVideos/day21-demo.mp4`. Видео и временные кадры не попадают в Git.
Обновлённая запись: 29 секунд, 1920×1080, H.264/AAC. В ней последовательно
подсвечиваются добавление документа Atlas, chunking, embeddings, SQLite,
side-by-side чанки и поиск `ORBIT-47`. Файл полностью декодирован через ffmpeg.

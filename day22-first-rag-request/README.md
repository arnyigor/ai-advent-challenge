# День 22. Первый RAG-запрос

🎥 **Видео-демо:** [day22-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/WDDTC9uBbH4gsA) — 48 секунд: живое сравнение ответа без RAG и с RAG, найденные чанки и результаты 10 контрольных вопросов.

Агент отвечает в двух режимах одной и той же LLM:

1. **без RAG:** вопрос сразу передаётся модели;
2. **с RAG:** вопрос превращается в embedding, из structure-aware SQLite-индекса Дня 21 выбираются top-4 чанка, затем контекст и вопрос передаются модели.

В ответе режима RAG видны найденные чанки, cosine score, `source`, `section` и ссылки `[N]`. Контрольный набор содержит ровно 10 вопросов; для каждого зафиксированы ожидаемые факты и источники. `evaluate.py` выполняет 20 LLM-запросов и сохраняет сравнение полноты ключевых фактов и recall источников.

## Запуск

Из корня репозитория:

```powershell
.\.venv\Scripts\python.exe -m pip install -r day22-first-rag-request\requirements.txt
.\.venv\Scripts\python.exe day22-first-rag-request\rag_agent.py
.\.venv\Scripts\python.exe day22-first-rag-request\web_server.py
```

Сервер напечатает локальный адрес. Модель можно заменить через `DAY22_MODEL` или `--model`, например `gemini:gemini-3.5-flash`. По умолчанию используется `deepseek:deepseek-v4-flash`; нужен `DEEPSEEK_API_KEY`. Значение ключа код не читает и не выводит.

Индекс берётся из `day21-document-indexing/data/indexes/structure.sqlite3`. Если его нет:

```powershell
.\.venv\Scripts\python.exe day21-document-indexing\pipeline.py
```

## Контрольные вопросы и отчёт

Набор находится в `control_questions.json`. У каждого элемента есть:

- `expectation` — что должно присутствовать в ответе;
- `required_terms` — наблюдаемые маркеры для воспроизводимой оценки;
- `expected_sources` — документы, которые должен найти retrieval.

Полный прогон:

```powershell
.\.venv\Scripts\python.exe day22-first-rag-request\evaluate.py
```

Отчёт сохраняется в `results/comparison.json` и автоматически появляется в веб-интерфейсе. Метрика `answer_score` проверяет наличие ожидаемых терминов, а `source_recall` — попадание ожидаемых документов в top-4. Это прозрачная smoke-оценка, а не замена экспертной проверке смысла.

### Фактический прогон DeepSeek V4 Flash

| Метрика | Без RAG | С RAG |
|---|---:|---:|
| Средняя полнота ожидаемых фактов | 31% | **95%** |
| Победы по 10 вопросам | 1 | **8** |
| Ничьи | 1 | 1 |

Recall ожидаемых источников в top-4 — **60%**. На вопросе о пагинации `tools/list` RAG проиграл: retrieval нашёл общие фрагменты Дня 16, но не чанк с `nextCursor`; модель корректно сообщила, что ответа в контексте нет. Этот случай оставлен в отчёте как пример того, что генерация не исправляет пропущенный retrieval.

## Проверка

```powershell
.\.venv\Scripts\python.exe -m py_compile day22-first-rag-request\rag_agent.py day22-first-rag-request\evaluate.py day22-first-rag-request\web_server.py
.\.venv\Scripts\python.exe -m pytest tests\test_day22_first_rag.py -q
node --check day22-first-rag-request\web\app.js
node --check day22-first-rag-request\record-video.mjs
```

## Видео

`node day22-first-rag-request/record-video.mjs` запускает локальный сервер, делает настоящий запрос без RAG и с RAG, показывает найденные источники и контрольный набор, затем сохраняет `ChallengeVideos/day22-demo.mp4`. Нужны Chrome, Node.js 22+ и ffmpeg; пути можно переопределить через `CHROME_PATH`, `PYTHON_PATH`, `FFMPEG_PATH`.

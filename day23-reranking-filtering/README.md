# День 23. Реранкинг и фильтрация

**Видео-демо:** [day23-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/sblYKx0N55JczA) — 40 секунд: query rewrite, top-8 кандидатов, similarity threshold 0.83, heuristic rerank, принятые/отсечённые чанки и сравнение качества двух режимов.

Второй этап retrieval не позволяет всем найденным чанкам автоматически попасть
в prompt. Проект сравнивает два режима на одном локальном индексе и одной LLM:

1. **Baseline RAG:** исходный вопрос → vector search top-4 → LLM.
2. **Improved RAG:** query rewrite → vector search top-8 → cosine threshold 0.83
   → heuristic rerank → максимум top-4 → LLM.

Интерфейс показывает rewritten query, полный список кандидатов, cosine score,
решение фильтра, lexical overlap, rerank score и финальный rank. Reranker прозрачно
смешивает 75% cosine similarity и 25% пересечения нормализованных терминов. CamelCase
и snake_case приводятся к одним токенам, поэтому `nextCursor` сопоставляется с
`next_cursor`. Если все результаты ниже порога, генерация с
нерелевантным контекстом не запускается.

## Запуск

Из корня репозитория:

```powershell
.\.venv\Scripts\python.exe -m pip install -r day23-reranking-filtering\requirements.txt
.\.venv\Scripts\python.exe day23-reranking-filtering\rag_agent.py
.\.venv\Scripts\python.exe day23-reranking-filtering\web_server.py
```

Используется индекс `day21-document-indexing/data/indexes/structure.sqlite3` и
контрольный набор `day22-first-rag-request/control_questions.json`. Если индекса
нет, сначала выполните pipeline Дня 21.

По умолчанию используется `deepseek:deepseek-v4-flash`. Настройки доступны через
аргументы `--model`, `--top-k-before`, `--top-k-after`, `--threshold` или через
`DAY23_MODEL`, `DAY23_TOP_K_BEFORE`, `DAY23_TOP_K_AFTER`,
`DAY23_SIMILARITY_THRESHOLD`.

## Сравнение качества

```powershell
.\.venv\Scripts\python.exe day23-reranking-filtering\evaluate.py
```

Скрипт выполняет оба режима для тех же 10 вопросов, считает полноту ожидаемых
фактов, recall источников, размер prompt, число принятых/отклонённых кандидатов и
сохраняет полный отчёт в `results/comparison.json`.

### Фактический прогон DeepSeek V4 Flash

| Метрика | Baseline RAG | Improved RAG |
|---|---:|---:|
| Средняя полнота ожидаемых фактов | 95% | **100%** |
| Recall ожидаемых источников | 60% | **65%** |
| Средний размер prompt | 3267 | 3623 |
| Победы по 10 вопросам | 0 | **1** |

Остальные 9 вопросов завершились вничью, проигрышей у improved режима нет. Из
8 найденных кандидатов в prompt в среднем проходят 3,7, а 4,3 отсеиваются.
На вопросе о пагинации `tools/list` релевантный `mcp_client.py` поднялся с
vector rank 8 на rerank 2 и добавил отсутствовавший в baseline факт о
`next_cursor`.

## Проверка

```powershell
.\.venv\Scripts\python.exe -m py_compile day23-reranking-filtering\rag_agent.py day23-reranking-filtering\evaluate.py day23-reranking-filtering\web_server.py
.\.venv\Scripts\python.exe -m pytest tests\test_day23_reranking_filtering.py -q
node --check day23-reranking-filtering\web\app.js
node --check day23-reranking-filtering\record-video.mjs
```

## Видео

`node day23-reranking-filtering/record-video.mjs` запускает реальный локальный
сервер, выполняет сравнение и сохраняет `ChallengeVideos/day23-demo.mp4`.
Нужны Chrome, Node.js 22+ и ffmpeg; пути переопределяются через `CHROME_PATH`,
`PYTHON_PATH`, `FFMPEG_PATH`.

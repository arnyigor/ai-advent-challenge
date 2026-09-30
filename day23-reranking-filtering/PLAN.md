# План реализации — День 23

## Зафиксированный контракт

Сравниваются два режима на одном индексе, одной embedding-модели и одной LLM:

- baseline: исходный вопрос → vector search top-4 → LLM;
- improved: query rewrite → vector search top-8 → similarity ≥ 0.83 → heuristic
  rerank (75% cosine + 25% lexical overlap) → top-4 → LLM.

Improved pipeline сохраняет полную трассировку кандидатов. Чанки ниже порога и
чанки за пределами финального top-K видны в отчёте, но не попадают в prompt.
Если после фильтрации ничего не осталось, система не подставляет шумовой контекст.

## Артефакты

1. `rag_agent.py` — rewrite, retrieval, filter и два режима.
2. `evaluate.py` — сравнение на 10 вопросах Дня 22.
3. `web_server.py` и `web/` — интерактивное сравнение и filter trace.
4. `record-video.mjs` и `VIDEO_SCRIPT.md` — воспроизводимое видео.
5. `tests/test_day23_reranking_filtering.py` — контрактные тесты.

## Критерии готовности

- Настройки top-K и threshold доступны через CLI и environment.
- В UI видны исходный и переписанный запросы, accepted/rejected чанки.
- Отчёт содержит качество ответов, source recall, размеры prompt и статистику фильтра.
- Python и JavaScript проходят syntax check, тесты проходят, web API запускается.
- MP4 создаётся автоматизированным сценарием и проверяется через ffmpeg.

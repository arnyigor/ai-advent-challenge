# Схема данных индекса помощника

## SQLite

Помощник хранит производный индекс в
`day31-developer-assistant/data/project.sqlite3`, вне Git.
Используется схема index_store.py дня 21:

| Таблица | Назначение и ключевые поля |
|---|---|
| index_runs | strategy, embedding_model, embedding_dim, chunk_size, corpus_hash, created_at |
| documents | source PRIMARY KEY, title, file, language, content_hash, char_count |
| chunks | chunk_id PRIMARY KEY, source, section, chunk_index, start_char, end_char, text, metadata_json |
| chunk_embeddings | chunk_id PRIMARY KEY, model, dim, embedding BLOB |
| chunk_fts | FTS5: chunk_id, source, text; tokenizer unicode61 |

documents.source — относительный POSIX-путь от корня репозитория. Chunk хранит
источник, секцию и границы символов для сверки с документом. Embedding —
нормализованный float32-вектор, dimension=384 у multilingual-e5-small.
Модель запроса должна совпадать с embedding_model и embedding_dim индекса.
corpus_hash — SHA-256 отсортированных пар source:content_hash. Проверка корпуса
обнаруживает изменение, добавление и удаление разрешённых документов.

## Данные ответа

`project` содержит repository, branch, head, detached из MCP.
`sources` — top-6 чанков с rank; ссылки [1], [2] относятся к их порядку в ответе.
`mcp` — фактические сведения initialize/tools/list/tools/call.
`usage`, `finish_reason` — значения API модели; length показывает обрезанный ответ.
Данные чата не сохраняются в SQLite. Реальные демонстрационные ответы можно
сохранить отдельно в evidence/ для проверки; это не корпус RAG.

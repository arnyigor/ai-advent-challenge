# Сценарий видео

1. Показать два pipeline: baseline top-4 и improved rewrite → top-8 → threshold → top-4.
2. Запустить контрольный вопрос о пагинации `tools/list`.
3. Показать исходный вопрос и rewritten query с сохранённым `nextCursor`.
4. Сравнить vector rank и heuristic rerank; показать поднятый релевантный чанк.
5. Сравнить ответы baseline и improved RAG, затем показать решения «принят/отсечён».
6. Завершить метриками 10 вопросов из сохранённого отчёта.

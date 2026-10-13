# День 32. Автоматическое AI-ревью кода

**Видео-демо:** [day32-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/n1mfQD3C50gSJQ) — 0:55, непрерывная запись браузера: запуск ревью, настоящий Git diff, RAG по документации и коду, живой ответ Gemini с багами, архитектурными проблемами и рекомендациями. Локальный запуск того же пайплайна, который используется в GitHub Action; 1600×900, H.264, 25 fps.

GitHub Action получает diff и изменённые файлы PR, ищет документацию и код
через SQLite FTS5 BM25 и передаёт контекст Gemini. Результат: потенциальные
баги, архитектурные проблемы и рекомендации с файлами, строками и источниками.

[Подробный анализ и план](PLAN.md) · [Workflow](../.github/workflows/day32-ai-review.yml)
· [Настоящее ревью демо](evidence/review.md) · [Сценарий видео](DEMO.md).

## Подключение GitHub

1. Добавить workflow, day32-ai-code-review/review.py и существующий tools/llm
   в базовую ветку репозитория. На первом PR, который только добавляет эти файлы,
   target workflow ещё не сможет использовать новую реализацию из base.
2. Settings → Secrets and variables → Actions: secret GEMINI_API_KEY.
   Переменная DAY32_MODEL необязательна; по умолчанию gemini-3.5-flash-lite
   как в дне 31. Доступность модели и квота зависят от вашего проекта Gemini.
3. Открыть или обновить non-draft PR. Actions → Day 32 AI code review:
   summary содержит review.md; артефакт содержит ревью, diff, RAG JSON и usage.

Код PR не выполняется. Не используется pull_request checkout и не устанавливаются
зависимости из head. Workflow работает с read-only contents permission; комментарий
в PR не публикуется. Для private repository fetch без credentials потребует отдельной
настройки аутентификации; текущая конфигурация рассчитана на этот public repository.
Fork PR тоже может вызвать модель и расходовать квоту: при публичном использовании
нужно определить политику допуска авторов/лимиты расходов. Содержимое отобранных
файлов и документации отправляется Gemini. Исключение секретных имён не обнаруживает
ключи, случайно записанные внутри обычного исходника.

## Локальный запуск

Python 3.12, Git, requests; для видео Chrome, Node.js 22+, ffmpeg и ffprobe.

```powershell
.\.venv\Scripts\python.exe -m pip install requests==2.32.5
.\.venv\Scripts\python.exe day32-ai-code-review\review.py
.\.venv\Scripts\python.exe day32-ai-code-review\review.py --base main --head HEAD --retrieve-only
# Ключ задаётся через окружение; не записывайте его в код.
.\.venv\Scripts\python.exe day32-ai-code-review\review.py --base main --head HEAD
.\.venv\Scripts\python.exe -m pytest tests\test_day32_review.py -q
```

Демо создаёт новый отдельный repo (повторный запуск требует нового пути):

```powershell
.\.venv\Scripts\python.exe day32-ai-code-review\demo.py
.\.venv\Scripts\python.exe day32-ai-code-review\server.py
# Во втором терминале:
node day32-ai-code-review/capture-demo.mjs
.\.venv\Scripts\python.exe day32-ai-code-review\record_video.py
```

## Проверено 13 октября 2026

Настоящие два Git-коммита в локальном временном repo. Реальный вызов
gemini-3.5-flash-lite завершился STOP: модель обнаружила неверный расчёт процента
и удаление валидации, сослалась на docs/architecture.md, pricing.py и checkout.py.
При новой записи через браузер использована gemini-3.5-flash: lite временно
возвращала HTTP 503. Новый живой ответ также завершился STOP; он сохранён в
evidence/result.json и показан на видео. Для повторения задайте
`$env:DAY32_MODEL = 'gemini-3.5-flash'` перед запуском server.py.
Это небольшая приёмочная выборка, а не измерение точности ревьюера.
Все 13 тестов прошли: 8 новых и 5 регрессионных тестов провайдеров дня 31.
Перед публикацией весь набор `python -m pytest tests -q`: 456 passed (92,60 с),
одно предупреждение deprecation в зависимости Starlette.
Автотесты проверяют Git/RAG, опасные ref, исключения файлов, бюджет и retrieval-only.
Приёмочная проверка: `python day32-ai-code-review/verify.py`.

Видео: локальный ChallengeVideos/day32-demo.mp4; непрерывная запись браузера:
нажатие «Запустить ревью», настоящий diff, найденные RAG-источники и живой ответ
Gemini. Время между кадрами сохранено; экраны не реконструируются.
Запуск GitHub Action пока не выполнен: после публикации кода в main настройте
secret GEMINI_API_KEY и откройте PR. Видео опубликовано на Яндекс.Диске:
размер загруженного файла совпал с локальным — 1 360 416 байт.
Семантическая точность каждого будущего ревью не гарантируется;
источники проверяются только по ID. Пропущенные файлы требуют ручного анализа.

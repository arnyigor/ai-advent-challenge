# День 32: анализ и план

## Что переносим из дня 31

День 31 отвечает на вопросы через semantic E5 RAG по README/docs и MCP для ветки.
У него нет diff, исходников в корпусе и триггера PR. Для ревью текущая ветка
недостаточна: нужны точные SHA события, merge-base и построчные изменения.
Переиспользуем tools.llm.Client и обработку Gemini, подход к evidence и монтажу.
MCP не нужен: Git CLI читает объекты непосредственно в runner.

## Контракт

Вход: локальный Git object database, base/head ref, каталог результата.
collect → base_sha, merge_base_sha, head_sha, changed_paths, diff, files,
sources (id/path/line/kind/text), index (объём/чанки/пропуски), skipped.
generate → text/model/usage/finish_reason. run сохраняет context.json,
diff.patch, review.md, result.json. retrieve-only не вызывает модель.
Без аргументов CLI показывает справку и завершается успешно.

## Архитектура и решения

1. Git diff merge-base→head соответствует внесённым PR изменениям. RAG строится
   по base SHA: PR не может переписать документацию и незаметно заменить контракт.
2. Изменённые файлы читаем через git show, нумеруем строки head; удаления имеют
   head=null. Переименования показываем как удаление/добавление. Symlinks не читаем.
3. SQLite FTS5 BM25: документация и код, чанки 40 строк с шагом 30; резервируем
   по четыре результата для каждого типа. Это lexical RAG, без embeddings.
   Плюс: воспроизводимый CPU-поиск в CI. Минус: хуже на синонимах и русских запросах
   к английскому коду; шумные слова diff могут ухудшать retrieval.
4. Ограничения: 24 000 символов/байт на исходный файл, 65 000 символов diff+files,
   3 000 000 символов корпуса. Большие файлы пропускаются целиком; это не полный
   обзор монорепозитория. Ограничения видны в context.json и итоговом ревью.
5. Gemini получает SYSTEM отдельно от JSON с недоверенным содержимым. Проверяем
   завершение STOP, разделы и существование номеров источников. Это не доказательство
   семантической верности и не абсолютная защита от prompt injection.
6. pull_request_target запускает доверенный workflow; checkout только base SHA.
   head загружаем как Git objects без checkout, импорта, тестов и установки PR deps.
   Ключ доступен только шагу генерации, GITHUB_TOKEN имеет contents:read.
   Выход: артефакт и job summary, без write permission и публикации комментариев.

## План проверки и результаты

- Временный репозиторий: сломать discount и удалить валидацию; проверить diff,
  документацию и checkout.py в retrieval; выполнить настоящий запрос модели.
- Проверить исключение секретных путей, oversized/binary/symlink, удаления,
  бюджет и невозможность подставить shell/options через ref.
- Проверить retrieve-only без вызова модели, синтаксис Python, CLI по умолчанию.
- Записать непрерывную работу браузера: запуск, получение diff, RAG и живой ответ.
- GitHub запуск после попадания workflow и скрипта в base branch и настройки ключа.
  Локальная симуляция не подменяет такой запуск.

## Источники решения по CI

GitHub: [события workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[безопасное использование pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target).
Обычный pull_request из fork не получает секреты. Поэтому здесь выбран target,
а untrusted PR code читается только как данные. Workflow пока использует version
tags actions, а не immutable SHA: для production стоит закрепить проверенные SHA.

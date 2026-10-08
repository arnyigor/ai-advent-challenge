# День 29. Оптимизация локальной LLM

**Видео-демо:** [day29-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/fXGbompX9XAvPA) — сравнение квантов, температуры и промптов, реальные ответы, память и скорость до/после, выбранный CPU-конфиг. 2:50, титры без звука.

**Статус: 2026-10-08 выбран и проверен конфиг для экономии RAM и повторяемости ответов.** Qwen3-1.7B Q4_K_M на CPU: temperature=0, max_tokens=1024, окно=4096, reasoning off. Исходный system prompt сохранён: новые варианты ухудшали отказ или обязательные условия. Измеренный пик RSS снизился примерно на 11%; качество не улучшилось, ускорения нет. Итоги: [RESULTS.md](RESULTS.md), конфиг: [optimized.json](optimized.json), план: [PLAN.md](PLAN.md).

Видео: [публичный MP4](https://yadi.sk/i/fXGbompX9XAvPA), 2:50, 1920×1080, H.264, 25 fps, титры без звука. Это монтаж сохранённых реальных результатов, без новых вызовов модели. Локальная копия: ChallengeVideos/day29-demo.mp4 (вне Git). Содержание и воспроизведение: [DEMO.md](DEMO.md).

## Использовать выбранную конфигурацию

Из корня репозитория запустить модель в отдельном терминале, затем выполнить вопрос в другом:

```powershell
day29-local-llm-optimization\run-cpu-model.bat
# В другом терминале; --inspect не вызывает модель
.\.venv\Scripts\python.exe day29-local-llm-optimization\ask.py --inspect
.\.venv\Scripts\python.exe day29-local-llm-optimization\ask.py 'Какой аварийный код Atlas, кто разрешает его использование и что нельзя повторять после восстановления соединения?'
```

ask.py читает полный prompt и параметры из optimized.json, проверяет SHA-256 prompt и использует URL 8081 из конфига. Переменные LOCAL_LLM_URL/MODEL от Strata не переопределяют этот адрес. run-cpu-model.bat: окно 4096, 8 потоков, reasoning off, --no-context-shift, лимит 1024. PORT/MODEL/LLAMA_SERVER можно переопределить вручную; при смене порта/модели согласуйте optimized.json. Чужой сервер не останавливается. Все шесть тестовых prompt с резервом 1024 занимали максимум 3115 токенов; произвольный длинный ввод может превысить окно и вызвать ошибку сервера. Максимальная наблюдённая генерация — 181 токен.

Неверные ссылки, ошибки MCP/RSS и отказ исправлять ложную предпосылку Atlas сохраняются. Настройки уменьшают память и вариативность текста, а не исправляют эти ошибки.

153 завершённых измеряемых вызова + 12 прогревов; отдельно один прерванный вызов и один успешный CLI smoke. **19 тестов дней 28/29 прошли.** Compact-профиль проверен по три раза на шести вопросах: нет пустых/обрезанных ответов, ответы совпали SHA-256 с temperature=0/окно 8192. ask.py проверен на реальной модели с совпадением SHA-256 найденного контекста. Все собственные серверы остановлены; Strata не затрагивалась.

```powershell
# Повторить контроль температуры в одном сервере
.\.venv\Scripts\python.exe day29-local-llm-optimization\cpu_experiment.py --run --quants Q4_K_M --profiles baseline temperature --repeats 3 --label temperature-repeat
# Повторить выбранный компактный вариант
.\.venv\Scripts\python.exe day29-local-llm-optimization\cpu_experiment.py --run --quants Q4_K_M --profiles compact --context 4096 --repeats 3 --label compact-repeat
# Обычный CLI через собственный сервер с автоматической остановкой
.\.venv\Scripts\python.exe day29-local-llm-optimization\cpu_experiment.py --run --quants Q4_K_M --context 4096 --smoke-ask --label smoke-repeat
```

Ниже сохранены команды исходного пилота. У cpu_experiment.py окно по умолчанию 8192, у выбранного run-cpu-model.bat — 4096. Дополнительные флаги: --case-ids для короткого скрининга, --reasoning on --reasoning-budget 512 для отдельного дорогого эксперимента. Reasoning on не выбран по умолчанию. Отзывы проверяет review_quality.py; оценки compact перенесены только при точном совпадении хешей ответа, контекста и system prompt с уже просмотренными ответами temperature.

Большая Strata не перезагружается. Основной эксперимент выполняет отдельный маленький CPU-сервер; альтернативный маршрут для Strata описан ниже. В benchmark.py окно и квантование только документируются, а cpu_experiment.py задаёт окно и файл весов при запуске собственного сервера.

**Уточнение: основной маршрут теперь Qwen3-1.7B на CPU**, Q2_K / существующий Q4_K_M / Q8_0 из одной ревизии Unsloth. Strata не используется. Загрузка и пилот:

```powershell
.\.venv\Scripts\python.exe day29-local-llm-optimization\download_quants.py
.\.venv\Scripts\python.exe day29-local-llm-optimization\benchmark.py --prepare
.\.venv\Scripts\python.exe day29-local-llm-optimization\cpu_experiment.py --run
# Затем выбранное квантование: пример, ещё не рекомендация
.\.venv\Scripts\python.exe day29-local-llm-optimization\cpu_experiment.py --run --quants Q4_K_M --profiles baseline prompt --repeats 3 --label prompt-final
```

Сервер запускается автоматически и последовательно на CPU, порт 8081, 8 потоков, окно 8192, thinking off, prompt cache off. Чужой процесс на порту не останавливается; при занятом порту запуск завершается ошибкой. Для повторного прогона задайте новый --label. В results/ сохраняются ответы, источники, конфигурация, RSS/CPU, время загрузки и журналы серверов. Скрипт останавливает только собственные процессы.

Из корня репозитория, без модели:

```powershell
.\.venv\Scripts\python.exe day29-local-llm-optimization\benchmark.py
.\.venv\Scripts\python.exe -m pytest tests/test_day29_optimization.py -q
```

Позже, когда ресурсы свободны, сохранить одинаковый RAG-контекст (E5 на CPU, без LLM):

```powershell
.\.venv\Scripts\python.exe day29-local-llm-optimization\benchmark.py --prepare
```

Начальный реальный эксперимент, **12 вызовов модели**. URL/id ниже из дня 28: перед запуском сверить текущие настройки.

```powershell
$env:LOCAL_LLM_URL = 'http://127.0.0.1:8083/v1'
$env:LOCAL_LLM_MODEL = 'qwen3.8-flash-next-iq3_s'
.\.venv\Scripts\python.exe day29-local-llm-optimization\benchmark.py --run --profiles baseline prompt --repeats 1 --output day29-local-llm-optimization\results\pilot.json
# 36 вызовов для выбранного профиля; prompt заменить на фактического победителя
.\.venv\Scripts\python.exe day29-local-llm-optimization\benchmark.py --run --profiles baseline prompt --repeats 3 --output day29-local-llm-optimization\results\final.json
```

Дополнительные профили: temperature, budget, candidate. --context-window, --quantization и --server-note записывают подтверждённые человеком настройки; ничего не меняют в сервере. Все вызовы последовательны и только на literal loopback, redirects/proxy отключены. Облачных вызовов нет. results/ исключён из Git.

Каждый вызов сохраняется сразу. Для источников откройте metadata.frozen_cases; заполните manual_quality (0/1/2) и quality_notes для каждого ответа по критериям PLAN. Сводка качества автоматически не вычисляется. Медиана относится к успешным вызовам; truncation и ошибки считать отдельно. GPU-замеры до/после относятся ко всему устройству и не измеряют пик; RAM, TTFT и чистая скорость декодирования этим кодом не измеряются. Отсутствие ответа и finish_reason=length сохраняются как наблюдения.

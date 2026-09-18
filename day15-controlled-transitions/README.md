# День 15. Контролируемые переходы состояний

**Видео-демо:** [day15-demo.mp4 на Яндекс.Диске](https://yadi.sk/d/K4aXX36VdDiK2w) — отказ на попытке реализовать задачу до утверждения плана и завершить её без валидации, возврат плана и реализации на доработку, сравнение DeepSeek V4 Flash и Qwen3.8-27B на одном снимке, пауза с восстановлением только по `task_id` и полный журнал разрешённых и отклонённых переходов.

Ассистент работает через явный жизненный цикл. Модели могут предложить действие, но изменить состояние способен только детерминированный `TransitionGuard`.

## Что реализовано

- декларативный контракт `lifecycle.json`;
- обязательное согласование плана до реализации;
- обязательная валидация до завершения;
- возврат плана на доработку и реализации после неудачной проверки;
- серверная блокировка прыжков между этапами;
- пауза и восстановление только по `task_id`;
- SQLite, оптимистические версии и аудит успешных/отклонённых попыток;
- сравнение `deepseek-v4-flash` и `qwen/qwen3.8-27b` через RouterAI на одном снимке.

## Жизненный цикл

```text
planning → plan_review → implementation → validation → completed
             ↘ planning        ↑             ↙
                       (возвраты на доработку)
```

`pause` — ортогональный флаг: этап не меняется, а любые переходы блокируются до `resume`.

## Запуск

```powershell
cd day15-controlled-transitions
python web_server.py
```

Для живого сравнения нужны `DEEPSEEK_API_KEY` и `ROUTERAI_API_KEY`. Без них весь локальный жизненный цикл продолжает работать, а карточка модели показывает её недоступность.

## Проверка

```powershell
python -m py_compile task_lifecycle.py task_store.py lifecycle_assistant.py model_comparison.py web_server.py
python -m pytest ../tests/test_day15_controlled_transitions.py -q
node --check web/app.js
node --check record-video.mjs
node record-video.mjs
```

Подробный план: [PLAN.md](PLAN.md). Сценарий записи: [VIDEO_SCRIPT.md](VIDEO_SCRIPT.md).


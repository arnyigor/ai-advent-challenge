# Day 4: Температура

## Что делает

Один зафиксированный промпт (Git rebase vs merge) прогоняется при температурах 0.0, 0.7 и 1.2 по 3 повтора каждое — между вызовами меняется только temperature. По сэмплам считаются метрики: self_similarity (повторяемость внутри одной температуры), TTR (тип-токен ratio), средний балл чеклиста фактов и деградации (обрывы, срыв языка, повторы).

## Стек

Python + tools/llm (общий транспорт Gemini/DeepSeek с ретраями, fallback по
цепочке моделей и опциональным стримингом — см. корневой README.md).

## Установка

```bash
pip install -r requirements.txt
```

## Настройка ключа

- `DEEPSEEK_API_KEY` — основной провайдер (не хранится в коде).
- `GEMINI_API_KEY` — fallback-цепочка, если DeepSeek недоступен.

## Запуск

```bash
python day04_temperature.py --mode text
python day04_temperature.py --mode json
```

## Демо

Видео: ChallengeVideos/day04-demo.mp4 (ссылка на Яндекс.Диск формируется submit-day.ps1)

## Структура

```
day04-temperature/
├── day04_temperature.py         # основной CLI-скрипт (text/json)
├── experiment.py                # промпт, preflight, матрица сэмплов, fallback по цепочке
├── metrics.py                   # self_similarity, TTR, чеклист фактов, деградации
├── web_server.py                # локальный web-копилот (SSE-стрим событий)
├── run-web.bat                  # запуск web-сервера
├── record-video.mjs             # запись демо-видео
├── web/                         # фронтенд (index.html, app.js, styles.css)
├── requirements.txt             # зависимости
└── README.md
```

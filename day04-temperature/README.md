# Day 4: Температура

## Что делает

<!-- TODO: 1-2 предложения о задаче дня -->

## Стек

Python + tools/llm (общий транспорт Gemini/DeepSeek с ретраями, fallback по
цепочке моделей и опциональным стримингом — см. корневой README.md).

## Установка

```bash
pip install -r requirements.txt
```

## Настройка ключа

Ключ должен быть в переменной окружения `GEMINI_API_KEY` (не хранится в коде).

## Запуск

```bash
python day04_temperature.py --mode text
python day04_temperature.py --mode json
```

## Демо

Видео: <!-- TODO: вставить ссылку после submit-day.ps1 -->

## Структура

```
day04-temperature/
├── day04_temperature.py         # основной скрипт
├── requirements.txt   # зависимости
└── README.md
```

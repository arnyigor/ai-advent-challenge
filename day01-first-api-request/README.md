# Day 1: First LLM API Request

## Что делает

Минимальный клиент для Gemini API — отправляет текстовый запрос,
получает ответ, выводит в консоль в виде мини-чата.

- Отправляет POST-запрос к Gemini API (generateContent)
- Разбирает JSON-ответ и достаёт сгенерированный текст
- Обрабатывает сетевые ошибки без падения скрипта
- Работает в режиме простого CLI-чата (цикл while, выход по exit)

## Стек

- Python 3.10+
- requests — HTTP-запросы, без SDK
- Модель: gemini-2.5-flash (бесплатный тариф Gemini API)

## Установка

```bash
pip install -r requirements.txt
```

## Настройка ключа

Ключ должен быть в переменной окружения `GEMINI_API_KEY` (не хранится
в коде). Подробная инструкция — в `tools/API_KEYS.md`.

## Запуск

```bash
python day1_llm.py
```

## Демо

Видео: https://yadi.sk/i/pL7IihvS8o5xGg

## Структура

```
day01-first-api-request/
├── day1_llm.py
├── requirements.txt
└── README.md
```

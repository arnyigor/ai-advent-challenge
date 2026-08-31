# API-ключи и токены

Единое место, где хранятся инструкции по настройке ключей для всех дней челленджа.
Ключи **никогда** не хардкодятся в коде — только переменные окружения.
Перед сабмитом прогоняй `tools/check-secrets.ps1` (ловит случайно попавшие ключи).

## Где взять ключи

| Провайдер | Переменная окружения | Где получить | Формат |
|---|---|---|---|
| Google Gemini | `GEMINI_API_KEY` | https://aistudio.google.com/apikey | `AIza...` |
| OpenAI | `OPENAI_API_KEY` | https://platform.openai.com/api-keys | `sk-...` |
| DeepSeek | `DEEPSEEK_API_KEY` | https://platform.deepseek.com/api_keys | `sk-...` |
| llama.cpp | `LLAMACPP_URL` (не ключ, адрес) | локальный сервер OpenAI-совместимый API | `http://127.0.0.1:8080` |
| Ollama | `OLLAMA_URL` (не ключ, адрес) | `ollama serve` | `http://127.0.0.1:11434` |

## Как задать (Windows / PowerShell)

Глобально для пользователя (переживёт перезапуск терминала):

```powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "твой_ключ", "User")
```

Временно, только в текущей сессии:

```powershell
$env:GEMINI_API_KEY = "твой_ключ"
```

После `SetEnvironmentVariable` уже открытые терминалы/IDE не подхватят переменную —
перезапусти их.

## Самодиагностика Gemini

`tools/check-gemini.ps1` — проверяет ключ: список моделей,
решает задачу с fallback по цепочке моделей, печатает ответ и расход токенов.

```powershell
powershell -ExecutionPolicy Bypass -File tools/check-gemini.ps1
```

## Проверка на утечки перед сабмитом

```powershell
powershell -ExecutionPolicy Bypass -File tools/check-secrets.ps1 -Path .
```

Скрипт ищет паттерны ключей (`AIza...`, `sk-...`, `Bearer ...`, `api_key = "..."`)
во всех `.py/.js/.json/.env/.ps1/.md` и блокирует сабмит, если что-то найдёт.

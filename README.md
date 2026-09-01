# AI Advent Challenge

Ежедневные задания челленджа. Каждый день — отдельная папка
dayNN-slug/ с кодом, README и (при необходимости) requirements.

## Структура репозитория

```
ai-advent-challenge/
├── day01-first-api-request/
├── day02-.../
├── tools/              # скрипты автоматизации (см. ниже)
├── .gitignore
└── README.md
```

## Видео — важно: НЕ в git

Видео-демо каждого дня хранится локально и заливается на Яндекс.Диск,
но никогда не попадает в git.

Причины:
- git плохо работает с большими бинарными файлами
- GitHub режет/жалуется на большие файлы
- видео и так нужно в вебе с нормальным плеером, а не в виде бинарника
  в репо

Это обеспечено строкой в .gitignore:
```
*.mp4
*.mov
*.mkv
```

Локальное хранение видео: ChallengeVideos\dayNN-demo.mp4

## Автоматическая заливка видео

Настроен через rclone (https://rclone.org) + Яндекс.Диск
(remote yandex_challenge).

Ежедневное использование — одна команда:
```powershell
.\tools\submit-day.ps1 -Day 2 -Video "ChallengeVideos\day02-demo.mp4"
```

Она сама:
1. Проверяет код (python -m py_compile)
2. Сканирует на утечку API-ключей (check-secrets.ps1)
3. Коммитит и пушит код в GitHub
4. Заливает видео на Яндекс.Диск (rclone copyto, папка
   AI Advent Challenge/Day NN/)
5. Получает публичную ссылку (rclone link)
6. Собирает итоговый текст сдачи и кладёт в буфер обмена

После этого — просто Ctrl+V в чат челленджа.

## Начать новый день

```powershell
.\tools\new-day.ps1 -Day 3 -Slug "structured-output" -Title "Structured Output"
```

Создаёт day03-structured-output/ с шаблоном README, challenge.json
и пустым файлом кода.

## Ручная заливка видео (если нужно вне submit-day.ps1)

Полный пошаговый workflow (mkdir → copyto → link → сверка размеров):
`tools/RCLONE_AGENT_GUIDE.md`. Быстрая версия:

```powershell
rclone mkdir "yandex_challenge:AI Advent Challenge/Day 01"
rclone copyto "ChallengeVideos\day01-demo.mp4" "yandex_challenge:AI Advent Challenge/Day 01/day01-demo.mp4" --yandex-upload-wait 2s
rclone link "yandex_challenge:AI Advent Challenge/Day 01/day01-demo.mp4"
```

## Что разрешено делать локальному AI-агенту

Кратко: настройка OAuth и rclone config — только вручную, агенту не давать.
Агенту разрешены только безопасные команды (ls/mkdir/copyto/link и т.п.),
запрещены config/sync/delete/move/purge — **полный список и workflow:
`tools/RCLONE_AGENT_GUIDE.md`** (он же — источник правды).

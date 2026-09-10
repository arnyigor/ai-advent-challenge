---
name: ship-day
description: Сдать день челленджа - залить готовое видео dayNN-demo.mp4 на Яндекс.Диск, вставить ссылку в README дня, закоммитить и запушить, выдать ссылки на видео и на папку дня. Использовать, когда пользователь говорит "залей видео", "сдай день", "выложи день N", "залей на яндекс, обнови описание, коммит, пуш" или просит ссылку на видео дня.
---

# Сдача дня челленджа

Финальный шаг дня: видео уже записано и проверено. Скилл заливает его,
проставляет ссылку в описание и пушит.

## Данные

- Видео: `ChallengeVideos/dayNN-demo.mp4` (NN — с ведущим нулём).
- Папка дня: `dayNN-<slug>/`, в ней `README.md` и `challenge.json` (title).
- Remote: `yandex_challenge`, путь `AI Advent Challenge/Day NN/dayNN-demo.mp4`.
- Репозиторий: `https://github.com/arnyigor/ai-advent-challenge`, ветка `main`.

Правила работы с rclone (что можно и что запрещено) — `tools/RCLONE_AGENT_GUIDE.md`.
Разрешены только `lsd/ls/mkdir/copyto/link/about`. `config`, `sync`, `move`,
`delete`, `purge` — запрещены, при необходимости остановиться и спросить.

## Шаги

1. **Проверить видео.** Файл существует, размер не подозрительно мал,
   `ffprobe` показывает ожидаемые fps и длительность.
2. **Убрать лишнее.** Удалить `__pycache__`, временные кадры и прочий мусор,
   порождённый записью. Чужие незакоммиченные файлы не трогать — сказать о них
   пользователю.
3. **Прогнать тесты**: `python -m pytest tests -q`. Красные тесты — не заливать.
4. **Залить:**
   ```bash
   rclone mkdir "yandex_challenge:AI Advent Challenge/Day NN"
   rclone copyto ChallengeVideos/dayNN-demo.mp4 "yandex_challenge:AI Advent Challenge/Day NN/dayNN-demo.mp4"
   rclone link "yandex_challenge:AI Advent Challenge/Day NN/dayNN-demo.mp4"
   ```
   Перезаливка того же пути сохраняет прежнюю публичную ссылку, так что
   обновлять видео можно без правки README.
5. **Обновить README дня.** Вверху строка в формате предыдущих дней:
   `**Видео-демо:** [dayNN-demo.mp4 на Яндекс.Диске](<ссылка>) — <что видно в ролике>`.
   Заодно сверить, что описание соответствует финальному состоянию кода и
   ролика (цифры, названия файлов, шаги запуска).
6. **Коммит и пуш.** Сообщение: `Day N: <title из challenge.json>`.
   Ветка `main`, пушить сразу.
7. **Ответ пользователю:** ссылка на видео и ссылка на папку дня на GitHub
   (`https://github.com/arnyigor/ai-advent-challenge/tree/main/dayNN-<slug>`).

## Альтернатива

`tools/submit-day.ps1 -Day N -Video "ChallengeVideos\dayNN-demo.mp4"` делает
шаги 3–4, 6 и собирает текст сдачи в буфер обмена, но не правит README.
Использовать её, если пользователь просит именно готовый текст для сдачи.

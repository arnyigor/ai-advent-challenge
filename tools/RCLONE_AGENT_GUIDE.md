# Гайд для локального агента: заливка видео на Яндекс.Диск

## Разрешено / запрещено

✅ Разрешено:
- `rclone lsd` — посмотреть папки
- `rclone ls` / `rclone lsl` / `rclone lsjson` — посмотреть файлы
- `rclone mkdir` — создать папку
- `rclone copyto` — залить конкретный файл
- `rclone link` — получить публичную ссылку
- `rclone about` — проверить квоту

❌ Запрещено безусловно:
- `rclone config*` (create/delete/update/edit) — OAuth настраивается только человеком вручную
- `rclone authorize`
- Чтение файла `rclone.conf` в любом виде (`cat`, `Get-Content`, поиск токена)
- `rclone sync` — удаляет "лишние" файлы на приёмнике, может стереть чужие данные
- `rclone move` / `rclone moveto` — удаляет файл из источника
- `rclone delete` / `rclone deletefile` / `rclone purge` / `rclone cleanup`
- Любой `find`/`Get-ChildItem -Recurse` по всему диску (D:, C:, G:) без указания конкретной подпапки — приводит к зависанию

Если что-то из списка "запрещено" кажется нужным для решения задачи — остановиться и спросить пользователя, а не выполнять самостоятельно.

## Константы окружения

```
REMOTE = yandex_challenge
ROOT_FOLDER = "AI Advance Challenge"
VIDEO_LOCAL_DIR = <папка с записанными видео>   (настраивается пользователем, напр. %USERPROFILE%\Videos\ChallengeVideos)
VIDEO_NAMING = dayNN-demo.mp4   (NN — номер дня с ведущим нулём, напр. day02-demo.mp4)
```

**RCLONE_EXE — определять динамически, не хардкодить путь:**
```powershell
# 1) попробовать PATH
$exe = (Get-Command rclone -ErrorAction SilentlyContinue).Source
# 2) fallback: типичный winget-путь без хардкода username
if (-not $exe) {
    $exe = (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "Rclone.Rclone_*" -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName '*\rclone.exe' } | Resolve-Path -ErrorAction SilentlyContinue | Select-Object -First 1).Path
}
```
Все команды rclone вызывать через:
```powershell
powershell.exe -NoProfile -Command "& '<RCLONE_EXE>' <команда> <аргументы>"
```
Если rclone не найден ни в PATH, ни в winget-папке — сообщить пользователю, не додумывать путь.

## Стандартный workflow: залить видео дня N

**Шаг 1 — проверить, что локальный файл существует и не пустой:**
```powershell
powershell.exe -NoProfile -Command "Get-Item '<VIDEO_LOCAL_DIR>dayNN-demo.mp4' | Select-Object Name, Length"
```
Если `Length` подозрительно маленький (меньше нескольких сотен КБ для реального видео) — сообщить пользователю и не продолжать, вероятно файл битый или не тот.

**Шаг 2 — проверить, что remote вообще доступен (не пытаться чинить, если недоступен):**
```powershell
powershell.exe -NoProfile -Command "& '<RCLONE_EXE>' lsd yandex_challenge:"
```
Если команда вернула ошибку (auth failed, invalid token и т.п.) — остановиться, показать пользователю точный текст ошибки. Это может значить, что токен истёк — чинить самостоятельно нельзя, это снова OAuth-зона.

**Шаг 3 — создать папку дня (безопасно вызывать даже если папка уже есть, mkdir идемпотентен):**
```powershell
powershell.exe -NoProfile -Command "& '<RCLONE_EXE>' mkdir 'yandex_challenge:AI Advance Challenge/Day NN'"
```

**Шаг 4 — залить видео:**
```powershell
powershell.exe -NoProfile -Command "& '<RCLONE_EXE>' copyto '<VIDEO_LOCAL_DIR>dayNN-demo.mp4' 'yandex_challenge:AI Advance Challenge/Day NN/dayNN-demo.mp4' --yandex-upload-wait 2s"
```
Флаг `--yandex-upload-wait 2s` обязателен — Яндекс.Диск иногда сообщает о завершении загрузки чуть раньше, чем реально готов файл, из-за чего следующая команда (`lsjson`/`link`) может вернуть ошибку 500.

**Шаг 5 — получить публичную ссылку:**
```powershell
powershell.exe -NoProfile -Command "& '<RCLONE_EXE>' link 'yandex_challenge:AI Advance Challenge/Day NN/dayNN-demo.mp4'"
```

**Шаг 6 — сверить размер (локальный vs залитый), обязательный шаг верификации:**
```powershell
powershell.exe -NoProfile -Command "Get-Item '<VIDEO_LOCAL_DIR>dayNN-demo.mp4' | Select-Object Length"
powershell.exe -NoProfile -Command "& '<RCLONE_EXE>' lsl 'yandex_challenge:AI Advance Challenge/Day NN'"
```
Размеры должны совпадать побайтово. Если не совпадают — не считать загрузку успешной, сообщить пользователю.

## Проверка структуры всего челленджа

**Посмотреть все папки дней на Диске:**
```powershell
powershell.exe -NoProfile -Command "& '<RCLONE_EXE>' lsd 'yandex_challenge:AI Advance Challenge'"
```

**Посмотреть содержимое конкретного дня:**
```powershell
powershell.exe -NoProfile -Command "& '<RCLONE_EXE>' lsjson 'yandex_challenge:AI Advance Challenge/Day NN'"
```
`lsjson` удобнее для программной обработки (даёт структурированные данные: имя, размер, дату изменения), `ls`/`lsl` — для быстрого визуального просмотра.

**Проверить квоту (не сканирует файлы, быстрая команда):**
```powershell
powershell.exe -NoProfile -Command "& '<RCLONE_EXE>' about yandex_challenge:"
```
НЕ использовать `rclone size` для этой цели — она рекурсивно обходит все файлы и может зависнуть на большом личном Диске.

**Сверить локальную структуру с git-репозиторием** (что дни совпадают между кодом и видео):
```powershell
# из корня репозитория — без абсолютных путей
Get-ChildItem . -Directory -Filter "day*"
Get-ChildItem <VIDEO_LOCAL_DIR> -Filter "day*-demo.mp4"
```
Полезно перед сдачей — убедиться, что для каждой папки дня в репозитории есть соответствующее видео.

## Типичные ошибки и что с ними делать

| Ошибка | Что делать |
|---|---|
| `couldn't read OAuth token` / `invalid character` | Токен в конфиге битый. НЕ чинить самостоятельно — это OAuth-зона, только пользователь. |
| `500 Internal Server Error` сразу после `copyto` | Забыт флаг `--yandex-upload-wait 2s`. Подождать 5-10 сек и повторить `lsjson`/`link` для уже залитого файла — сам файл обычно цел. |
| `directory not found` при `mkdir`/`copyto` | Проверить точное написание пути — регистр и пробелы в `"AI Advance Challenge/Day NN"` должны совпадать один в один с уже существующими папками. |
| Размер файла на Диске не совпадает с локальным | Файл залился не полностью (обрыв сети). Повторить `copyto` с тем же путём — перезапишет. |
| `rclone` не находится (command not found) | PATH не подхватился в bash-сессии — использовать полный путь через `RCLONE_EXE`, не рассчитывать на глобальный `rclone`. |

## После успешной заливки

Финальный отчёт пользователю должен включать:
- Путь к локальному файлу и его размер
- Путь на Яндекс.Диске
- Публичную ссылку (`rclone link`)
- Подтверждение совпадения размеров (шаг верификации)
- Если что-то не удалось — точный текст ошибки, без попыток "угадать" исправление в OAuth-зоне

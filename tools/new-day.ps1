param(
    [Parameter(Mandatory=$true)][int]$Day,
    [Parameter(Mandatory=$true)][string]$Slug,
    [Parameter(Mandatory=$true)][string]$Title
)

$d = "{0:D2}" -f $Day
$root = Split-Path -Parent $PSScriptRoot
$folder = Join-Path $root "day$d-$Slug"
New-Item -ItemType Directory -Path $folder -Force | Out-Null

$readme = @"
# Day ${Day}: $Title

## Что делает

<!-- TODO: 1-2 предложения о задаче дня -->

## Стек

<!-- TODO: язык, ключевые библиотеки, модель/API -->

## Установка

``````bash
pip install -r requirements.txt
``````

## Настройка ключа

Ключ должен быть в переменной окружения ``GEMINI_API_KEY`` (не хранится в коде).

## Запуск

``````bash
python day$Day.py
``````

## Демо

Видео: <!-- TODO: вставить ссылку после submit-day.ps1 -->

## Структура

``````
day$d-$Slug/
├── day$Day.py         # основной скрипт
├── requirements.txt   # зависимости
└── README.md
``````
"@

Set-Content -Path "$folder\README.md" -Value $readme -Encoding UTF8

@{ day = $Day; title = $Title; entrypoint = "day$Day.py" } | ConvertTo-Json | Set-Content "$folder\challenge.json"
New-Item -ItemType File -Path "$folder\day$Day.py" -Force | Out-Null
New-Item -ItemType File -Path "$folder\requirements.txt" -Force | Out-Null

Write-Host "Создано: $folder" -ForegroundColor Green

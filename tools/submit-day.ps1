param(
    [Parameter(Mandatory=$true)][int]$Day,
    [Parameter(Mandatory=$true)][string]$Video
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$config = Get-Content "$PSScriptRoot\config.json" | ConvertFrom-Json
$d = "{0:D2}" -f $Day

$dayFolder = Get-ChildItem -Path $root -Directory | Where-Object { $_.Name -match "^day$d-" }
if (-not $dayFolder) { throw "Папка day$d-* не найдена" }
Write-Host "Папка: $($dayFolder.Name)" -ForegroundColor Cyan

$pyFiles = Get-ChildItem -Path $dayFolder.FullName -Filter *.py -Recurse
if ($pyFiles) {
    python -m py_compile $pyFiles.FullName
    if ($LASTEXITCODE -ne 0) { throw "Ошибка компиляции Python" }
}

& "$PSScriptRoot\check-secrets.ps1" -Path $root
if ($LASTEXITCODE -ne 0) { throw "Обнаружены секреты" }

$title = "Day $Day"
if (Test-Path "$($dayFolder.FullName)\challenge.json") {
    $title = (Get-Content "$($dayFolder.FullName)\challenge.json" | ConvertFrom-Json).title
}

Push-Location $root
git add -A
if (git diff --cached --quiet) {
    Write-Host "Нет изменений для коммита, пропускаю commit." -ForegroundColor Yellow
} else {
    git commit -m "Day $Day`: $title"
}
git push
$commit = git rev-parse --short HEAD
Pop-Location

$videoName = $config.videoFilePattern -replace '\{day\}', $d
$remotePath = "$($config.videoRemote):$($config.videoDirectory)/Day $d/$videoName"
rclone copyto $Video $remotePath
$videoLink = (rclone link $remotePath).Trim()

$result = @"
AI Advance Challenge — Day $d

Код:
$($config.githubRepo)/tree/$($config.branch)/$($dayFolder.Name)

Видео:
$videoLink

Commit:
$commit
"@

Write-Host "`n$result" -ForegroundColor Green
$result | Set-Clipboard
Write-Host "`nСкопировано в буфер обмена." -ForegroundColor Green

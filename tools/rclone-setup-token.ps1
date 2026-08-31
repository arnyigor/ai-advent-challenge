$ErrorActionPreference = 'Stop'
# rclone ищем в PATH (установленный через winget/choco rclone обычно уже там)
$rcloneCmd = Get-Command rclone -ErrorAction SilentlyContinue
if ($rcloneCmd) {
    $rclone = $rcloneCmd.Source
} else {
    # fallback: типичный путь winget-установки (без хардкода username — через %LOCALAPPDATA%)
    $winget = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "Rclone.Rclone_*" -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "*\rclone.exe" } | Resolve-Path -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $winget) { throw 'rclone not found in PATH or in the winget packages folder' }
    $rclone = $winget.Path
}
# удалить битый remote из прошлой попытки
& $rclone config delete yandex 2>$null
# лог авторизации лежит рядом с этим скриптом
$authLog = Join-Path $PSScriptRoot 'rclone-auth.log'
$tok = (Get-Content $authLog | Where-Object { $_ -match '^\{"access_token' } | Select-Object -First 1)
if (-not $tok) { throw "token line not found in $authLog" }
& $rclone config create yandex yandex config_is_local=false token=$tok

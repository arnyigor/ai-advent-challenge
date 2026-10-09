# Day 30: start the HTTP gateway (single worker) in front of the loopback model.
#
#   powershell -ExecutionPolicy Bypass -File run-service.ps1
#   powershell -ExecutionPolicy Bypass -File run-service.ps1 -BindHost 192.168.1.50
#
# Keys: set SERVICE_API_KEYS="main=<key>;ratelimit=<key2>" or create keys.json
# (gitignored) next to this script. See README, section "Ключи доступа".
param(
    [string]$BindHost = $(if ($env:SERVICE_HOST) { $env:SERVICE_HOST } else { "127.0.0.1" }),
    [int]$Port = $(if ($env:SERVICE_PORT) { [int]$env:SERVICE_PORT } else { 8091 }),
    [string]$BackendUrl = $(if ($env:BACKEND_URL) { $env:BACKEND_URL } else { "http://127.0.0.1:8081" }),
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"
$DayDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path (Split-Path -Parent $DayDir) ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$KeysFile = Join-Path $DayDir "keys.json"

if (-not $env:SERVICE_API_KEYS -and -not (Test-Path $KeysFile)) {
    Write-Host "No API keys: set SERVICE_API_KEYS or create $KeysFile" -ForegroundColor Red
    Write-Host 'Example: $env:SERVICE_API_KEYS = "main=<key>;ratelimit=<key2>"'
    exit 1
}

$ModelKeyFile = Join-Path $DayDir "model-key.txt"
if (-not $env:MODEL_API_KEY -and (Test-Path $ModelKeyFile)) {
    $env:MODEL_API_KEY = (Get-Content $ModelKeyFile -Raw).Trim()
    Write-Host "Model key loaded from model-key.txt (used as Bearer to llama-server)"
}
if (-not $env:MODEL_API_KEY) { Write-Host "MODEL_API_KEY is not set: the loopback backend stays open to local processes" -ForegroundColor Yellow }

$env:SERVICE_HOST = $BindHost
$env:SERVICE_PORT = "$Port"
$env:BACKEND_URL = $BackendUrl

Write-Host "Gateway: http://${BindHost}:${Port}  backend: $BackendUrl  worker: 1"
Write-Host "Health:  curl.exe http://${BindHost}:${Port}/health"
Write-Host "Model:   http://127.0.0.1:8081 (loopback, never exposed directly)"

Set-Location -LiteralPath $DayDir
# The script owns its log: uvicorn writes to stderr, and redirecting a native
# command's stderr from a scheduled task both buffers and can turn into a
# terminating error under $ErrorActionPreference = "Stop".
if (-not $LogPath) { $LogPath = Join-Path $DayDir "evidence\gateway.log" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
Start-Transcript -Path $LogPath -Append | Out-Null
# Keep the package importable no matter which directory the task scheduler used.
$env:PYTHONPATH = $DayDir
$env:PYTHONUNBUFFERED = "1"
Write-Host "Working directory: $((Get-Location).Path)"
Write-Host "Python: $Python (exists: $(Test-Path -LiteralPath $Python))"
$ErrorActionPreference = "Continue"   # the child writes its log to stderr
& $Python -m llmgateway
$code = $LASTEXITCODE
Write-Host "gateway exited with code $code"
Stop-Transcript | Out-Null
exit $code

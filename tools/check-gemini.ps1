# ============================================================
# GEMINI REST API — ПОЛНАЯ ПРОВЕРКА С FALLBACK ПО МОДЕЛЯМ
# Ключ берётся из переменной окружения GEMINI_API_KEY (без хардкода)
# Запуск:  powershell -ExecutionPolicy Bypass -File check-gemini.ps1
# ============================================================

Add-Type -AssemblyName System.Net.Http

# --- 1. Ключ из окружения (глобально) ---
$apiKey = $env:GEMINI_API_KEY
if (-not $apiKey) {
    Write-Host "❌ GEMINI_API_KEY не задана. Задайте: setx GEMINI_API_KEY \"...\" (или $env:GEMINI_API_KEY='...' в сессии)" -ForegroundColor Red
    exit 1
}
Write-Host "Ключ: ***" -ForegroundColor DarkGray

# --- 2. Базовый вызов generateContent ---
function Invoke-GeminiChat {
    param(
        [string]$model,
        [string]$prompt,
        [string]$apiKey,
        [int]$maxRetries = 3
    )

    $client = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds(60)
    $client.DefaultRequestHeaders.Add("x-goog-api-key", $apiKey)

    $bodyJson = @{
        contents = @(@{ parts = @(@{ text = $prompt }) })
    } | ConvertTo-Json -Depth 5

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($bodyJson)
    $url = "https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent"

    for ($i = 0; $i -lt $maxRetries; $i++) {
        $content = New-Object System.Net.Http.ByteArrayContent(,$bytes)
        $content.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/json")

        try {
            $response = $client.PostAsync($url, $content).Result
        } catch {
            return [PSCustomObject]@{ Model=$model; Status="EXCEPTION"; Text=$_.Exception.InnerException.Message; PromptTok=0; ThoughtTok=0; OutTok=0 }
        }

        $respBytes = $response.Content.ReadAsByteArrayAsync().Result
        $rawText = [System.Text.Encoding]::UTF8.GetString($respBytes)
        $code = $response.StatusCode.value__

        # 429 = лимит, ждём. 503 = перегрузка, короткая пауза.
        if ($code -eq 429) {
            $wait = 10 * ($i + 1)
            Write-Host "  [$model] 429 (rate limit), жду $wait сек... (попытка $($i+1)/$maxRetries)" -ForegroundColor DarkYellow
            Start-Sleep -Seconds $wait
            continue
        }
        if ($code -eq 503) {
            Write-Host "  [$model] 503 (модель перегружена), пауза 5 сек..." -ForegroundColor DarkYellow
            Start-Sleep -Seconds 5
            continue
        }

        if ($code -ne 200) {
            return [PSCustomObject]@{ Model=$model; Status="HTTP $code"; Text=$rawText; PromptTok=0; ThoughtTok=0; OutTok=0 }
        }

        try {
            $parsed = $rawText | ConvertFrom-Json
        } catch {
            return [PSCustomObject]@{ Model=$model; Status="BAD_JSON"; Text=$rawText; PromptTok=0; ThoughtTok=0; OutTok=0 }
        }

        $answerText = $parsed.candidates[0].content.parts[0].text
        $usage = $parsed.usageMetadata
        $thoughtTok = if ($usage.thoughtsTokenCount) { $usage.thoughtsTokenCount } else { 0 }

        return [PSCustomObject]@{
            Model      = $model
            Status     = "OK"
            Text       = $answerText
            PromptTok  = $usage.promptTokenCount
            ThoughtTok = $thoughtTok
            OutTok     = $usage.candidatesTokenCount
        }
    }

    return [PSCustomObject]@{ Model="NONE"; Status="FAILED_AFTER_RETRY"; Text="не удалось после $maxRetries попыток"; PromptTok=0; ThoughtTok=0; OutTok=0 }
}

# --- 3. Fallback по цепочке моделей ---
function Invoke-GeminiWithFallback {
    param(
        [string[]]$modelChain,
        [string]$prompt,
        [string]$apiKey
    )

    foreach ($m in $modelChain) {
        Write-Host "Пробую $m..." -ForegroundColor Cyan -NoNewline
        $r = Invoke-GeminiChat -model $m -prompt $prompt -apiKey $apiKey -maxRetries 2

        if ($r.Status -eq "OK") {
            Write-Host " -> OK" -ForegroundColor Green
            return $r
        }

        Write-Host " -> $($r.Status), пробую следующую модель" -ForegroundColor Yellow
    }

    return [PSCustomObject]@{ Model="NONE"; Status="ALL_FAILED"; Text="Все модели в цепочке недоступны"; PromptTok=0; ThoughtTok=0; OutTok=0 }
}

# --- 4. Список моделей, доступных ключу ---
Write-Host "`n=== Доступные Gemini-модели (flash/pro) ===" -ForegroundColor Cyan
$listClient = New-Object System.Net.Http.HttpClient
$listClient.DefaultRequestHeaders.Add("x-goog-api-key", $apiKey)
try {
    $listResp = $listClient.GetAsync("https://generativelanguage.googleapis.com/v1beta/models").Result
    $listBytes = $listResp.Content.ReadAsByteArrayAsync().Result
    $listText = [System.Text.Encoding]::UTF8.GetString($listBytes)
    if ($listResp.StatusCode.value__ -eq 200) {
        ($listText | ConvertFrom-Json).models |
            Where-Object { $_.name -like "*flash*" -or $_.name -like "*pro*" } |
            Select-Object name, displayName | Format-Table -AutoSize
    } else {
        Write-Host "HTTP $($listResp.StatusCode.value__): $listText" -ForegroundColor Red
    }
} catch {
    Write-Host "Ошибка: $($_.Exception.Message)" -ForegroundColor Red
}

# --- 5. Задание ---
$task = @'
У тебя есть три задачи с дедлайнами и зависимостями:
- Задача A: дедлайн 15:00, зависит от B
- Задача B: дедлайн 14:45, независима
- Задача C: дедлайн 15:00, зависит от A и от самой себя

Верни ТОЛЬКО валидный JSON строго по схеме:
{"order": ["..."], "warnings": ["..."]}

order - порядок выполнения задач с учетом зависимостей.
warnings - список проблем во входных данных, если они есть.
Если во входных данных есть логическое противоречие, обязательно укажи его в warnings. Не игнорируй его и не придумывай решение, которое его обходит.
'@

# --- 6. Цепочка fallback (дешёвая/быстрая -> дороже -> preview) ---
# цепочка: дешёвая/быстрая -> дороже (модели проверены по /models для этого ключа)
$chain = @(
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-2.5-flash"
)

Write-Host "`n=== Запуск с fallback ===" -ForegroundColor Cyan
$final = Invoke-GeminiWithFallback -modelChain $chain -prompt $task -apiKey $apiKey

Write-Host "`n=== РЕЗУЛЬТАТ ===" -ForegroundColor Cyan
Write-Host "Модель: $($final.Model)" -ForegroundColor White
Write-Host $final.Text
if ($final.Status -eq "OK") {
    Write-Host "Tokens: prompt=$($final.PromptTok) thoughts=$($final.ThoughtTok) output=$($final.OutTok)" -ForegroundColor DarkGray
}

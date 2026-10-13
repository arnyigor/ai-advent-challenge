param(
    [string]$LlamaServer = $env:LLAMA_SERVER,
    [string]$ModelFile = $env:DAY31_MODEL_FILE
)
$ErrorActionPreference = 'Stop'
if (-not $LlamaServer -or -not (Test-Path -LiteralPath $LlamaServer -PathType Leaf)) {
    throw 'Specify -LlamaServer or LLAMA_SERVER: path to llama-server.exe'
}
if (-not $ModelFile -or -not (Test-Path -LiteralPath $ModelFile -PathType Leaf)) {
    throw 'Specify -ModelFile or DAY31_MODEL_FILE: path to GGUF'
}
$day31Port = if ($env:DAY31_MODEL_PORT) { [int]$env:DAY31_MODEL_PORT } else { 8085 }
$day31Alias = if ($env:DAY31_MODEL_ALIAS) { $env:DAY31_MODEL_ALIAS } else { 'day31-qwen3.8-27b' }
$day31Layers = if ($env:DAY31_GPU_LAYERS) { [int]$env:DAY31_GPU_LAYERS } else { 99 }
if (Get-NetTCPConnection -State Listen -LocalPort $day31Port -ErrorAction SilentlyContinue) {
    throw "Port $day31Port is occupied; choose DAY31_MODEL_PORT"
}
& $LlamaServer -m $ModelFile --host 127.0.0.1 --port $day31Port --alias $day31Alias `
    --gpu-layers $day31Layers --ctx-size 8192 --parallel 1 --threads 8 --reasoning off `
    --n-predict 1024 --batch-size 256 --ubatch-size 128
exit $LASTEXITCODE

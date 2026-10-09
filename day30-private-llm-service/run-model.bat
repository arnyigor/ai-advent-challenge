@echo off
rem Day 30: the only model of this project - Qwen3-1.7B Q4_K_M on CPU.
rem Loopback only (127.0.0.1); the LAN-facing part is the gateway on port 8091 (8090 is Strata).
rem MODEL_API_KEY (if set) protects the model itself: the gateway sends it as
rem Bearer on every backend call, so a local process cannot use the model alone.
setlocal
rem Pinned model and port: plain set, so a machine-wide PORT variable cannot move them
set "LLAMA_SERVER=G:\AIModels\llamacpp\llama-win-cuda-12.4-x64\llama-server.exe"
set "MODEL=G:\AIModels\SmallAgents\Qwen3-1.7B\Qwen3-1.7B-Q4_K_M.gguf"
set "PORT=8081"
if not defined MODEL_API_KEY if exist "%~dp0model-key.txt" set /p MODEL_API_KEY=<"%~dp0model-key.txt"
if not exist "%LLAMA_SERVER%" (echo llama-server not found: %LLAMA_SERVER% & exit /b 1)
if not exist "%MODEL%" (echo GGUF model not found: %MODEL% & exit /b 1)
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul && (echo Port %PORT% is already in use ^(not started by this script^); not starting a second model & exit /b 1)
set "KEY_ARG="
if defined MODEL_API_KEY (set "KEY_ARG=--api-key %MODEL_API_KEY%") else (echo WARNING: MODEL_API_KEY is not set; the loopback backend stays open to local processes)
echo Loading Qwen3-1.7B Q4_K_M on CPU, ctx 4096, 1 slot, port %PORT%
"%LLAMA_SERVER%" -m "%MODEL%" --device none --gpu-layers 0 --no-kv-offload --no-op-offload --ctx-size 4096 --parallel 1 --threads 8 --host 127.0.0.1 --port %PORT% --alias day30-qwen3-1.7b --reasoning off --no-cache-prompt --no-context-shift --n-predict 1024 --cors-origins localhost %KEY_ARG%

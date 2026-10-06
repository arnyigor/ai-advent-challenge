@echo off
setlocal
if not defined LLAMA_SERVER set "LLAMA_SERVER=G:\AIModels\llamacpp\llama-win-cuda-12.4-x64\llama-server.exe"
if not defined MODEL set "MODEL=G:\AIModels\SmallAgents\Qwen3-1.7B\Qwen3-1.7B-Q4_K_M.gguf"
if not exist "%LLAMA_SERVER%" (echo llama-server not found & exit /b 1)
if not exist "%MODEL%" (echo GGUF model not found & exit /b 1)
"%LLAMA_SERVER%" -m "%MODEL%" --device none --gpu-layers 0 --no-kv-offload --no-op-offload --ctx-size 8192 --parallel 1 --threads 8 --host 127.0.0.1 --port 8084 --alias qwen3-1.7b-cpu --reasoning off --n-predict 1024

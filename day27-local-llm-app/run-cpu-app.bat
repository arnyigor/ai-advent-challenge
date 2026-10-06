@echo off
setlocal
set "LOCAL_LLM_URL=http://127.0.0.1:8084/v1"
set "LOCAL_LLM_MODEL=qwen3-1.7b-cpu"
set "DAY27_WEB_PORT=8792"
node "%~dp0server.mjs"

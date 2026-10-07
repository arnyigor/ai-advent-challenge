@echo off
setlocal
if not defined LOCAL_LLM_URL set "LOCAL_LLM_URL=http://127.0.0.1:8083/v1"
if not defined LOCAL_LLM_MODEL set "LOCAL_LLM_MODEL=qwen3.8-flash-next-iq3_s"
"%~dp0..\.venv\Scripts\python.exe" "%~dp0server.py"

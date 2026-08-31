#!/usr/bin/env bash
# Запуск llm-demo (Web + API). Нужен только Node.js 18+.
cd "$(dirname "$0")"
echo
echo "  ✦ llm-demo: http://localhost:3000"
echo "  (Ctrl+C — остановить)"
exec node server.mjs

# Day 03 — Reasoning Modes

**Видео-демо:** [day03-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/vGg9g05mcEcrmg)

Одна задача → четыре способа рассуждения → четыре результата → сравнение.

- `direct` — прямой ответ (без указаний о рассуждении)
- `cot` — «решай пошагово»
- `self_prompt` — мета-промпт (модель сначала составляет промпт, потом решает)
- `panel` — группа экспертов (три роли в одном промпте, один вызов)

Бюджет на одну демонстрацию: 1 + 1 + 2 + 1 = 5 вызовов.

## Current Implementation Status

Done in the UI/runner architecture slice:

- Added structured `StageResult` records to every `MethodResult`.
- Added intermediate failure propagation: `self_prompt` and `panel` stop after a failed/truncated/blocked stage instead of continuing with damaged context.
- Changed direct prompting to use only the task text plus the shared answer contract.
- Made `ANSWER:` parsing case-insensitive for `ANSWER:`, `Answer:`, and `answer:`.
- Run `verify_gold()` before JSON and text execution paths.
- Added structured runner events and reporters: `NullReporter`, `PlainReporter`, `DashboardReporter`, and `RecordingReporter`.
- Added a Rich dashboard with header, current task, method cards, live score, failures, progress, and Pareto summary.
- Added `--ui auto|dashboard|plain|none`.
- Added full run persistence through `runs` in the JSON document, including per-stage data.
- Added `--out` for saving a run and `--replay-results` for rendering saved runs without API calls.
- Added `rich` to Day 3 requirements.
- Added regression tests for stages, intermediate truncation, parser casing, JSON run persistence, and reporter stage events.

Done in the web cockpit slice:

- Added `web_server.py`: local static server plus JSON APIs for tasks, models, saved results, and SSE runs.
- Added `web/index.html`, `web/styles.css`, and `web/app.js`.
- Web run is **one selected task, one pass, four fixed methods** — the browser cannot narrow the method set or run a multi-task benchmark.
- `panel` is a **single prompt / single API call** with three expert roles (analyst / engineer / critic) defined inside the prompt.
- Method cards are structured around `PROMPT SENT → MODEL RESPONSE → FINAL ANSWER`; `self_prompt` shows both calls separately.
- Added a working **STOP** button: `cancel_event`, `POST /api/runs/{id}/cancel`, cooperative cancellation between stages/methods, `STOPPING` state, and an `ExperimentCancelled` event.
- Methods are named with the assignment wording: `Прямой ответ / Решай пошагово / Мета-промпт / Группа экспертов`.
- Results tab shows a single-task comparison table (answer / correct / calls / tokens / time) instead of a family matrix, self-consistency, or a statistical winner.
- Added JSON upload, saved-result loading, and a demo data mode so the cockpit can be inspected without spending API quota.
- Imported Day 1 model references into the web selector:
  - Active for Day 3 Gemini runner: `gemini-3.5-flash-lite`, `gemini-3.5-flash`, `gemini-3.6-flash`, `gemini-3.7-flash`, `gemini-2.5-flash`.
  - Listed as planned provider expansion from Day 1: `llama.cpp/qwen-27b`, `ollama/llama3.2`, `deepseek/deepseek-chat`, `openai/gpt-4o-mini`, `routerai/qwen/qwen3.8-27b`, `mock/echo-1`.

Run locally:

```powershell
python day03-reasoning-modes\web_server.py --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765/
```

Verified:

- `python -m py_compile` for Day 3 modules.
- `pytest -q` for the full repository.
- JSON error path with missing `GEMINI_API_KEY` remains clean JSON.
- Dashboard replay smoke test runs without API calls.
- Web cockpit smoke test: `/`, `/api/tasks`, and `/api/models` respond from the local server.

## Remaining Work

- Add a low/high comparison screen on real `run-low.json` / `run-high.json` files.
- Add responsive layout snapshot tests at 80, 120, and 160 columns.
- Run real low/high benchmark files and save them under `day03-reasoning-modes/results/`.
- Wire non-Gemini Day 1 providers into the Day 3 experiment runner if cross-provider execution is needed.
- Prepare the final video and submission package.

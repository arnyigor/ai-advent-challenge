# Day 5: Версии моделей

**Видео-демо:** [day05-demo.mp4 на Яндекс.Диске](https://yadi.sk/i/PSIM6g2U_N72NA)

Один и тот же запрос на генерацию Python-функции выполняется на девяти моделях:
трёх Qwen2.5-Coder через Hugging Face, двух Gemini, DeepSeek и трёх локальных
Qwen от 1.7B CPU до 27B GPU.

## Модели

- [Qwen2.5-Coder-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct) — слабая.
- [Qwen2.5-Coder-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct) — средняя.
- [Qwen2.5-Coder-32B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct) — сильная.
- Gemini 3.5 Flash, Gemini 3.6 Flash и DeepSeek V4 Flash — API-контроль:
  другое семейство, но тот же prompt и измеримая цена.
- [Qwen3 1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) Q4_K_M — слабая
  локальная модель на CPU через llama.cpp.
- [Qwen3.5 4B](https://ollama.com/library/qwen3.5:4b) в кванте Q4_K_M —
  малая локальная контрольная модель через Ollama.
- [Qwen3.8-27B GGUF](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF)
  в кванте IQ4_XS — дополнительная контрольная модель через OpenAI-compatible llama.cpp.

HF-модели зафиксированы на одном провайдере `nscale`. Цена берётся из живого
каталога HF Router в момент запуска и считается по фактическим input/output
tokens. Для локальной модели API-стоимость равна нулю; дополнительно снимаются
пиковые VRAM, загрузка GPU и мощность через `nvidia-smi`.

## Настройка

Нужен `HF_TOKEN` с разрешением **Make calls to Inference Providers** — через
переменную окружения или локальное хранилище после `hf auth login`.
Локальный сервер задаётся отдельно, без адреса в коде:

```powershell
$env:LOCAL_LLM_URL = "http://127.0.0.1:<порт>"
$env:OLLAMA_URL = "http://127.0.0.1:<порт>"
$env:LOCAL_CPU_LLM_URL = "http://127.0.0.1:<порт>"
```

## Запуск

```powershell
pip install -r requirements.txt
python day05_model_versions.py --repeats 3
python day05_model_versions.py --mode json --out results/latest.json
python day05_model_versions.py --local-only --repeats 1
run-web.bat
```

Если URL локального сервера или ключ API не задан, соответствующая модель
пропускается. В итоговой таблице Qwen 3B/7B/32B остаются основной шкалой размеров,
а Gemini и DeepSeek явно помечены как API-контроль, чтобы не путать влияние
размера и семейства.

## Что измеряется

- end-to-end latency и время до первого токена;
- input/output tokens и tokens/s;
- стоимость вызова и сумма по модели;
- результат 10 автоматических тестов сгенерированного кода;
- размер модели в миллиардах параметров;
- для local: фактический пик VRAM/GPU/power.
- для CPU-local: пиковые RAM и загрузка CPU процесса сервера.

Облачный API не раскрывает реальную VRAM сервера, поэтому для HF
ресурсоёмкость обозначается числом параметров, скоростью и стоимостью, а не
выдуманной оценкой памяти.

## Зафиксированный результат

Три повтора, 4 сентября 2026 года. Время и токены — медиана, цена — сумма
трёх вызовов. Качество — среднее число пройденных тестов из 10.

| Модель | Тесты | Время | Ток/с | Токены | Цена / 3 |
|---|---:|---:|---:|---:|---:|
| HF Qwen 3B | 5.7 | 3.42 с | 193.5 | 662 | $0.000067 |
| HF Qwen 7B | 3.7 | 3.22 с | 144.8 | 466 | $0.000052 |
| HF Qwen 32B | 7.0 | 13.22 с | 39.5 | 526 | $0.000360 |
| Gemini 3.5 Flash | 6.7* | 15.97 с | 68.3 | 1055 | $0.020331 |
| Gemini 3.6 Flash | 10.0 | 31.19 с | 24.2 | 640 | $0.008368 |
| DeepSeek V4 Flash | 10.0 | 3.23 с | 149.4 | 488 | $0.001003 |
| Local Qwen 1.7B CPU | 3.0 | 38.08 с | 17.5 | 667 | $0 |
| Local Qwen 4B GPU | 3.0 | 5.08 с | 163.0 | 813 | $0 |
| Local Qwen 27B GPU | 10.0 | 15.11 с | 44.3 | 669 | $0 |

\* Gemini 3.5 дважды прошла 10/10, но один из трёх вызовов вернул неполный
ответ; сбой оставлен в статистике как показатель надёжности.

CPU-сервер 1.7B достиг 51% суммарной загрузки и 6.8 ГБ RAM при контексте 40960.
Общий пик VRAM системы во время GPU-прогонов составил 15.7 ГБ; для 4B это
включает одновременно загруженный сервер 27B, поэтому отдельно также полезно
смотреть на размер весов Ollama — 3.4 ГБ.

Максимальное качество показали Gemini 3.6, DeepSeek V4 и local 27B. Среди них
DeepSeek оказался самым быстрым; local 27B не имеет API-цены, но занял почти всю
16-ГБ VRAM. На этом prompt топовые модели уже похожи на микроскоп для забивания
гвоздей: качество достигло потолка, а время и цена продолжают расти.

## Источники

- [HF Inference Providers](https://huggingface.co/docs/inference-providers/index)
- [HF Pricing and Billing](https://huggingface.co/docs/inference-providers/pricing)
- [HF Chat Completion API](https://huggingface.co/docs/inference-providers/tasks/chat-completion)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [DeepSeek API pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)

Видео сохраняется локально как `ChallengeVideos/day05-demo.mp4`, загружается
на Яндекс.Диск и не попадает в git.

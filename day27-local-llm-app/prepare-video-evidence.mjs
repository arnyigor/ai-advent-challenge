// Snapshot of actual local process/API/logs; contains no fabricated generation data.
import {readFileSync,writeFileSync} from 'node:fs';
const base=new URL('./',import.meta.url);
const data=JSON.parse(readFileSync(new URL('results/cpu-video-evidence.json',base),'utf8').replace(/^\uFEFF/,''));
const log=readFileSync(new URL('results/llama-cpu.stderr.log',base),'utf8');
const timings=log.split(/\r?\n/).filter(line=>line.includes('total time')).slice(-3);
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const proc=Array.isArray(data.process)?data.process[0]:data.process;
if(!proc?.CommandLine.includes('--device none')||data.health.status!=='ok')throw Error('CPU evidence not confirmed');
writeFileSync(new URL('web/demo-evidence.html',base),`<!doctype html><html lang="ru"><meta charset="utf-8"><title>День 27 · Подтверждение CPU</title><link rel="stylesheet" href="/demo-evidence.css"><body><small>ДЕНЬ 27 · СОХРАНЁННЫЙ СНИМОК ФАКТИЧЕСКИХ ДАННЫХ</small><h1>Модель работает локально на CPU</h1><section><h2>Процесс и параметры запуска</h2><p><strong>${escape(proc.Name)}</strong> · PID ${escape(proc.ProcessId)}</p><pre>${escape(proc.CommandLine)}</pre></section><section><h2>Ответ локального API</h2><p>http://127.0.0.1:8084/health → <strong>${escape(data.health.status)}</strong><br>/v1/models → <strong>${escape(data.models[0].id)}</strong><br>Контекст: ${escape(data.models[0].meta.n_ctx)} токенов</p></section><section><h2>Настоящий журнал последних трёх запросов</h2><pre>${escape(timings.join('\n'))}</pre></section><small>Снимок: ${escape(data.capturedAt)}. Команда прочитана из процесса Windows; строки времени — из журнала llama-server.</small></body></html>`);

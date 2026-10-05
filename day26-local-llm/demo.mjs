#!/usr/bin/env node
import {writeFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

export const cases = [
  {id: 'simple', title: '1 · Простой запрос', prompt: 'Назови столицу Франции. Ответь одним словом.', check: s => /^Париж[.!]?$/iu.test(s.trim())},
  {id: 'reasoning', title: '2 · Расчёт с условиями', prompt: 'Три товара стоят по 1200 рублей. Скидка 15% на товары, доставка 300 рублей без скидки. Покажи расчёт и итоговую сумму в рублях.', check: s => /(?<![\d.,])3[\s\u00a0]*360(?![\d]|[.,]\d)/.test(s)},
  {id: 'code', title: '3 · Код и граничные случаи', prompt: 'Напиши JavaScript-функцию uniqueStable(values), которая убирает дубликаты, сохраняя порядок. Не изменяй входной массив. Покажи примеры для [3,1,3,2,1] и []. Кратко укажи временную сложность. Не используй внешние библиотеки.', check: null},
];

export function config(env = process.env) {
  if (!env.LOCAL_LLM_URL || !env.LOCAL_LLM_MODEL) throw Error('Задайте LOCAL_LLM_URL (полный API base URL с /v1) и LOCAL_LLM_MODEL из настроек Strata.');
  const url = new URL(env.LOCAL_LLM_URL);
  // Literal loopback only: no remote hosts, credentials, DNS or redirect fallback.
  if (url.protocol !== 'http:' || !['127.0.0.1', '[::1]'].includes(url.hostname) || url.username || url.password || url.search || url.hash) throw Error('Разрешён только http://127.0.0.1 или http://[::1] без credentials/query/hash.');
  const timeout = Number(env.LOCAL_LLM_TIMEOUT_MS || 180000);
  if (!Number.isSafeInteger(timeout) || timeout < 1 || timeout > 2147483647) throw Error('Некорректный LOCAL_LLM_TIMEOUT_MS.');
  return {base: url.href.replace(/\/$/, ''), model: env.LOCAL_LLM_MODEL, timeout};
}

export async function request(cfg, prompt) {
  const start = performance.now();
  // ASSUMPTION: Strata exposes OpenAI-compatible non-streaming chat completions.
  // Verify with the running Strata instance; no Strata-specific options assumed.
  const response = await fetch(`${cfg.base}/chat/completions`, {
    method: 'POST', redirect: 'error', signal: AbortSignal.timeout(cfg.timeout),
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({model: cfg.model, messages: [{role: 'user', content: prompt}], stream: false}),
  });
  if (!response.ok) throw Error(`HTTP ${response.status}`);
  const body = await response.json();
  const answer = body.choices?.[0]?.message?.content;
  if (typeof answer !== 'string' || !answer.trim()) throw Error('API не вернул непустой choices[0].message.content.');
  return {answer, elapsedMs: Math.round(performance.now() - start), returnedModel: body.model ?? null, usage: body.usage ?? null, finishReason: body.choices[0].finish_reason ?? null};
}

const escape = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
export function render(report) {
  return `<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>День 26 · Локальная LLM</title>
<style>body{background:#101827;color:#ecf2ff;font:20px/1.55 system-ui;max-width:1100px;margin:48px auto;padding:0 24px 96px}h1{font-size:42px}h2{color:#79e2c0}article,header{background:#1a2639;padding:28px;border-radius:18px;margin-bottom:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:18px/1.6 ui-monospace}small{color:#b4c5dc}b{color:#79e2c0}</style>
<header><small>AI ADVENT CHALLENGE / ДЕНЬ 26</small><h1>Локальная LLM · Strata</h1><p>${escape(report.base)}<br>Запрошенная модель: <b>${escape(report.model)}</b></p><p>${escape(report.startedAt)} · HTTP-ответы: ${report.results.filter(r => !r.error).length}/3</p><small>Реальные ответы текущего прогона. Loopback не доказывает локальный инференс: отдельно покажите процесс Strata и загруженную модель. Проверки ниже — частичные, не оценка качества модели.</small></header>
${report.results.map(r => `<article><h2>${escape(r.title)}</h2><small>ЗАПРОС</small><pre>${escape(r.prompt)}</pre><small>${r.error ? 'ОШИБКА' : 'ОТВЕТ'}</small><pre>${escape(r.error || r.answer)}</pre><p>${r.elapsedMs ?? '—'} мс · Модель API: ${escape(r.returnedModel ?? 'не указана')} · finish_reason: ${escape(r.finishReason ?? 'не указан')}</p><small>Проверка: ${escape(r.validation)}<br>Usage API: ${escape(JSON.stringify(r.usage ?? null))}</small></article>`).join('')}
<footer>Независимые запросы · Без облачного fallback · Код модели не исполняется автоматически</footer></html>`;
}

export async function run(cfg) {
  const report = {startedAt: new Date().toISOString(), base: cfg.base, model: cfg.model, results: []};
  for (const item of cases) {
    console.log(`\n${item.title}\n> ${item.prompt}`);
    let result = {id: item.id, title: item.title, prompt: item.prompt};
    try {
      const reply = await request(cfg, item.prompt);
      result = {...result, ...reply, validation: item.check ? (item.check(reply.answer) ? 'Частичная проверка пройдена' : 'Частичная проверка не пройдена') : 'Нужна ручная проверка кода и примеров'};
      console.log(`${reply.answer}\n[${reply.elapsedMs} мс] ${result.validation}`);
    } catch (error) {
      result = {...result, error: error.message, validation: 'Нет ответа'};
      console.error(`Ошибка: ${error.message}`);
    }
    report.results.push(result);
  }
  return report;
}

async function main() {
  if (process.argv.includes('--help')) {
    console.log('Задайте LOCAL_LLM_URL=http://127.0.0.1:<порт>/v1 и LOCAL_LLM_MODEL=<model id>, затем node day26-local-llm/demo.mjs. Результаты: results/<timestamp>/{report.json,report.html}.');
    return;
  }
  const cfg = config();
  const report = await run(cfg);
  const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), 'results', report.startedAt.replace(/[:.]/g, '-'));
  await mkdir(dir, {recursive: true});
  await writeFile(path.join(dir, 'report.json'), JSON.stringify(report, null, 2));
  await writeFile(path.join(dir, 'report.html'), render(report));
  console.log(`\nОтчёт: ${dir}`);
  if (report.results.some(r => r.error)) process.exitCode = 1;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => {console.error(error.message); process.exitCode = 1;});
}

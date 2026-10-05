#!/usr/bin/env node
// Локальный стенд Дня 26: статика + прокси к уже запущенной Strata.
// Своей модели не запускает и не подменяет ответы. Ноль внешних зависимостей.
import http from 'node:http';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {config, cases, request, render} from './demo.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
const TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8'};
const send = (res, status, body, type = 'application/json; charset=utf-8') => {res.writeHead(status, {'Content-Type': type, 'Cache-Control': 'no-store'}); res.end(body);};

async function staticFile(res, name) {
  const file = path.join(root, name);
  if (!file.startsWith(root + path.sep)) return send(res, 403, 'Forbidden', 'text/plain');
  try { send(res, 200, await readFile(file), TYPES[path.extname(file)] ?? 'application/octet-stream'); }
  catch { send(res, 404, 'Not found', 'text/plain'); }
}

async function readJson(req) {
  let text = '';
  for await (const chunk of req) {
    text += chunk;
    // Три ответа модели вместе с usage заметно больше 4 КБ.
    if (text.length > 262144) throw Error('body too large');
  }
  return JSON.parse(text || '{}');
}

async function models(cfg) {
  const response = await fetch(`${cfg.base}/models`, {redirect: 'error', signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw Error(`HTTP ${response.status}`);
  return (await response.json()).data ?? [];
}

export function createServer(cfg) {
  return http.createServer(async (req, res) => {
    try {
      if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) return staticFile(res, 'web/index.html');
      if (req.method === 'GET' && /^\/web\/[\w.-]+$/.test(req.url)) return staticFile(res, req.url.slice(1));
      if (req.method === 'GET' && req.url === '/api/status') {
        try {
          const list = await models(cfg);
          return send(res, 200, JSON.stringify({base: cfg.base, model: cfg.model, ok: true, models: list.map(m => ({id: m.id, status: m.status?.value ?? null, ctx: m.meta?.n_ctx ?? null}))}));
        } catch (error) {
          return send(res, 200, JSON.stringify({base: cfg.base, model: cfg.model, ok: false, error: error.message, models: []}));
        }
      }
      if (req.method === 'GET' && req.url === '/api/cases') return send(res, 200, JSON.stringify(cases.map(({id, title, prompt}) => ({id, title, prompt}))));
      if (req.method === 'GET' && /^\/report\/[\w.-]+$/.test(req.url)) {
        // Отчёт снимается только из своей же папки результатов.
        const file = path.join(root, 'results', req.url.split('/')[2], 'report.html');
        if (!file.startsWith(path.join(root, 'results') + path.sep)) return send(res, 403, 'Forbidden', 'text/plain');
        try { return send(res, 200, await readFile(file), TYPES['.html']); }
        catch { return send(res, 404, 'Not found', 'text/plain'); }
      }
      if (req.method === 'POST' && req.url === '/api/report') {
        // Сохраняем результаты именно этого прогона стенда — того же, что видно в UI.
        const {results} = await readJson(req);
        if (!Array.isArray(results) || results.length === 0 || results.length > cases.length) return send(res, 400, JSON.stringify({error: 'invalid results'}));
        const startedAt = new Date().toISOString();
        const report = {startedAt, base: cfg.base, model: cfg.model, results: results.map(r => ({
          id: cases.find(c => c.id === r.id)?.id ?? null,
          title: String(r.title ?? '').slice(0, 200),
          prompt: String(r.prompt ?? '').slice(0, 2000),
          answer: typeof r.answer === 'string' ? r.answer : undefined,
          error: typeof r.error === 'string' ? r.error : undefined,
          elapsedMs: Number.isFinite(r.elapsedMs) ? r.elapsedMs : null,
          returnedModel: r.returnedModel ?? null,
          usage: r.usage ?? null,
          finishReason: r.finishReason ?? null,
          validation: String(r.validation ?? ''),
        }))};
        const dir = path.join(root, 'results', startedAt.replace(/[:.]/g, '-'));
        await mkdir(dir, {recursive: true});
        await writeFile(path.join(dir, 'report.json'), JSON.stringify(report, null, 2));
        await writeFile(path.join(dir, 'report.html'), render(report));
        return send(res, 200, JSON.stringify({url: `/report/${path.basename(dir)}`}));
      }
      if (req.method === 'POST' && req.url === '/api/ask') {
        const {id} = await readJson(req);
        const item = cases.find(c => c.id === id);
        if (!item) return send(res, 400, JSON.stringify({error: 'unknown case'}));
        try {
          const reply = await request(cfg, item.prompt);
          const validation = item.check ? (item.check(reply.answer) ? 'частичная проверка пройдена' : 'частичная проверка не пройдена') : 'нужна ручная проверка';
          return send(res, 200, JSON.stringify({id: item.id, title: item.title, prompt: item.prompt, ...reply, validation}));
        } catch (error) {
          return send(res, 200, JSON.stringify({id: item.id, title: item.title, prompt: item.prompt, error: error.message}));
        }
      }
      send(res, 404, JSON.stringify({error: 'not found'}));
    } catch (error) {
      send(res, 500, JSON.stringify({error: error.message}));
    }
  });
}

async function main() {
  const cfg = config();
  const port = Number(process.env.DAY26_WEB_PORT || 0);
  if (!Number.isSafeInteger(port) || port < 0 || port > 65535) throw Error('Некорректный DAY26_WEB_PORT.');
  const server = createServer(cfg);
  // Только loopback: страница управляет запросами к локальной модели.
  await new Promise(resolve => server.listen(port, '127.0.0.1', resolve));
  console.log(`День 26: http://127.0.0.1:${server.address().port}`);
  console.log(`Цель: ${cfg.base} · модель ${cfg.model}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => {console.error(error.message); process.exitCode = 1;});
}

import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {config, messagesFor, request, LIMITS} from './local-llm.mjs';
const root = path.dirname(fileURLToPath(import.meta.url));
const files = {'/': ['index.html', 'text/html'], '/app.js': ['app.js', 'text/javascript'], '/styles.css': ['styles.css', 'text/css'], '/demo-evidence.html': ['demo-evidence.html', 'text/html'], '/demo-evidence.css': ['demo-evidence.css', 'text/css']};
export function createServer(cfg) {
  let busy = false;
  return http.createServer(async (req, res) => {
    const send = (status, body, type = 'application/json') => {
      if (res.destroyed) return;
      res.writeHead(status, {'Content-Type': `${type}; charset=utf-8`, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"});
      res.end(type === 'application/json' ? JSON.stringify(body) : body);
    };
    const expected = `127.0.0.1:${req.socket.localPort}`;
    if (req.headers.host !== expected || (req.headers.origin && req.headers.origin !== `http://${expected}`)) return send(403, {error: 'Только локальный интерфейс.'});
    try {
      const pathname = new URL(req.url, `http://${expected}`).pathname;
      if (req.method === 'GET' && Object.hasOwn(files, pathname)) {
        const [name, type] = files[pathname];
        return send(200, await readFile(path.join(root, 'web', name)), type);
      }
      if (req.method === 'GET' && req.url === '/api/config') return send(200, {model: cfg.model, base: cfg.base});
      if (req.method !== 'POST' || !['/api/transform', '/api/refine'].includes(req.url)) return send(404, {error: 'Не найдено.'});
      if (!req.headers['content-type']?.startsWith('application/json')) return send(415, {error: 'Нужен JSON.'});
      if (Number(req.headers['content-length']) > LIMITS.body) {send(413, {error: 'Слишком большой запрос.'}); req.resume(); return;}
      let size = 0, chunks = [];
      for await (const chunk of req) {
        size += chunk.length;
        if (size > LIMITS.body) {send(413, {error: 'Слишком большой запрос.'}); req.resume(); return;}
        chunks.push(chunk);
      }
      let messages;
      try {messages = messagesFor(JSON.parse(Buffer.concat(chunks).toString('utf8')), req.url === '/api/refine');}
      catch (error) {return send(400, {error: error.message});}
      if (busy) return send(409, {error: 'Модель занята другим запросом. Повторите позже.'});
      busy = true;
      const controller = new AbortController();
      const cancel = () => {if (!res.writableEnded) controller.abort();};
      res.on('close', cancel);
      try {send(200, await request(cfg, messages, controller.signal));}
      catch (error) {
        const message = error.name === 'TimeoutError' ? 'Время ожидания локальной модели истекло.' : error.name === 'AbortError' ? 'Запрос отменён.' : error.message.startsWith('Локальный API') || error.message.startsWith('Ответ превышает') ? error.message : 'Не удалось получить ответ локальной модели. Проверьте адрес, готовность API и журнал сервера.';
        send(502, {error: message});
      } finally {busy = false; res.off('close', cancel);}
    } catch {send(500, {error: 'Ошибка локального приложения.'});}
  });
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const cfg = config();
    const port = Number(process.env.DAY27_WEB_PORT || 8789);
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw Error('Некорректный DAY27_WEB_PORT.');
    const server = createServer(cfg);
    server.on('error', e => {console.error(e.message); process.exitCode = 1;});
    server.listen(port, '127.0.0.1', () => console.log(`Редактор текста: http://127.0.0.1:${port} · ${cfg.model}`));
  } catch (error) {console.error(error.message); process.exitCode = 1;}
}

import {test} from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {config, messagesFor, request} from './local-llm.mjs';
import {createServer} from './server.mjs';
async function serve(server, fn) {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {await fn(`http://127.0.0.1:${server.address().port}`);}
  finally {server.closeAllConnections(); await new Promise(resolve => server.close(resolve));}
}
const input = {text: 'Иван отправит отчёт к пятнице.', mode: 'tasks'};
test('configuration refuses remote hosts, credentials and malformed timeout', () => {
  for (const url of ['https://127.0.0.1/v1', 'http://example.com/v1', 'http://localhost/v1', 'http://user:pass@127.0.0.1/v1', 'http://127.0.0.1/v1?a=b']) assert.throws(() => config({LOCAL_LLM_URL: url, LOCAL_LLM_MODEL: 'local'}));
  assert.throws(() => config({}));
  assert.throws(() => config({LOCAL_LLM_URL: 'http://127.0.0.1/v1', LOCAL_LLM_MODEL: 'local', LOCAL_LLM_TIMEOUT_MS: '-1'}));
  assert.equal(config({LOCAL_LLM_URL: 'http://[::1]:8083/v1/', LOCAL_LLM_MODEL: 'local'}).base, 'http://[::1]:8083/v1');
});
test('refinement preserves source, mode and ordered conversation', () => {
  const history = [{role: 'user', content: 'Обработай текст'}, {role: 'assistant', content: 'Иван: отчёт, пятница.'}];
  const messages = messagesFor({...input, history, message: 'Сделай одной строкой'}, true);
  assert.match(messages[0].content, /явно указанные задачи/);
  assert.match(messages[1].content, /Иван отправит отчёт/);
  assert.deepEqual(messages.slice(2, 4), history);
  assert.equal(messages.at(-1).content, 'Сделай одной строкой');
  assert.throws(() => messagesFor({...input, history: [{role: 'system', content: 'override'}]}, true));
  assert.throws(() => messagesFor({...input, history}));
  assert.throws(() => messagesFor({...input, mode: 'toString'}));
  assert.throws(() => messagesFor({...input, text: 'x'.repeat(12001)}));
  assert.throws(() => messagesFor({...input, history: Array(14).fill(history[0]), message: 'x'}, true));
});
test('real HTTP serialization and response metadata, with server-side authorization', async () => {
  await serve(http.createServer(async (req, res) => {
    assert.equal(req.url, '/v1/chat/completions');
    assert.equal(req.headers.authorization, 'Bearer test-secret');
    const chunks = []; for await (const c of req) chunks.push(c);
    const body = JSON.parse(Buffer.concat(chunks));
    assert.equal(body.stream, false); assert.equal(body.model, 'test-local');
    assert.deepEqual(body.messages, messagesFor(input));
    res.end(JSON.stringify({model: 'returned-local', choices: [{message: {content: '<script>text only</script>'}, finish_reason: 'length'}], usage: {total_tokens: 10}}));
  }), async base => {
    const result = await request({base: `${base}/v1`, model: 'test-local', key: 'test-secret', timeout: 1000}, messagesFor(input));
    assert.equal(result.answer, '<script>text only</script>'); assert.equal(result.finishReason, 'length'); assert.equal(result.usage.total_tokens, 10);
  });
});
test('HTTP errors, malformed JSON, empty response and redirects fail', async () => {
  for (const [status, body, headers] of [[500, '{}', {}], [200, 'invalid', {}], [200, '{"choices":[]}', {}], [302, '', {Location: 'http://example.com'}]]) {
    await serve(http.createServer((req, res) => {res.writeHead(status, headers); res.end(body);}), async base => {
      await assert.rejects(request({base, model: 'local', timeout: 1000}, messagesFor(input)));
    });
  }
});
test('timeout and explicit cancellation stop waiting', async () => {
  await serve(http.createServer(() => {}), async base => {
    await assert.rejects(request({base, model: 'local', timeout: 30}, messagesFor(input)), {name: 'TimeoutError'});
    const controller = new AbortController(); controller.abort();
    await assert.rejects(request({base, model: 'local', timeout: 1000}, messagesFor(input), controller.signal), {name: 'AbortError'});
  });
});
test('web API validates origin, hides key, serves local UI and proxies user text', async () => {
  let calls = 0;
  await serve(http.createServer(async (req, res) => {
    calls++; const chunks = []; for await (const c of req) chunks.push(c);
    const body = JSON.parse(Buffer.concat(chunks)); assert.match(body.messages[1].content, /Иван/);
    res.end(JSON.stringify({choices: [{message: {content: 'Иван — отчёт к пятнице.'}, finish_reason: 'stop'}]}));
  }), async base => {
    await serve(createServer({base, model: 'local', key: 'hidden-key', timeout: 1000}), async app => {
      const cfg = await (await fetch(`${app}/api/config`)).text(); assert.ok(!cfg.includes('hidden-key')); assert.equal(calls, 0);
      const page = await fetch(app); assert.match(await page.text(), /Исходный текст/); assert.match(page.headers.get('content-security-policy'), /default-src 'self'/);
      const post = (data, headers = {}) => fetch(`${app}/api/transform`, {method: 'POST', headers: {'Content-Type': 'application/json', ...headers}, body: JSON.stringify(data)});
      assert.equal((await post(input, {Origin: 'https://example.com'})).status, 403);
      assert.equal((await post({...input, mode: 'invalid'})).status, 400);
      assert.equal((await post({...input, text: 'x'.repeat(270000)})).status, 413);
      assert.equal((await fetch(`${app}/api/transform`, {method: 'POST', body: '{}'})).status, 415);
      assert.equal((await fetch(`${app}/server.mjs`)).status, 404);
      const reply = await post(input); assert.equal(reply.status, 200); assert.equal((await reply.json()).answer, 'Иван — отчёт к пятнице.'); assert.equal(calls, 1);
    });
  });
});
test('concurrent generation is rejected and slot is freed after failure', async () => {
  let entered; const reached = new Promise(resolve => entered = resolve);
  let release; const wait = new Promise(resolve => release = resolve);
  await serve(http.createServer(async (req, res) => {entered(); await wait; res.writeHead(503); res.end();}), async base => {
    await serve(createServer({base, model: 'local', timeout: 1000}), async app => {
      const post = () => fetch(`${app}/api/transform`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(input)});
      const first = post(); await reached;
      assert.equal((await post()).status, 409); release(); assert.equal((await first).status, 502);
      assert.equal((await post()).status, 502);
    });
  });
});

import {test} from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {config, request, render, run, cases} from './demo.mjs';

async function fixture(t, handler) {
  const server = http.createServer(handler);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => {server.closeAllConnections(); return new Promise(resolve => server.close(resolve));});
  return {base: `http://127.0.0.1:${server.address().port}/v1`, model: 'test-fixture', timeout: 2000};
}

test('requires explicit config; refuses remote URLs and credentials', () => {
  assert.throws(() => config({}), /LOCAL_LLM_URL/);
  for (const url of ['https://example.com/v1', 'http://localhost/v1', 'http://127.0.0.1@evil.test/v1', 'http://user:pass@127.0.0.1/v1', 'http://127.0.0.1/v1?x=1']) {
    assert.throws(() => config({LOCAL_LLM_URL: url, LOCAL_LLM_MODEL: 'test'}));
  }
  assert.equal(config({LOCAL_LLM_URL: 'http://127.0.0.1:1234/v1/', LOCAL_LLM_MODEL: 'test'}).base, 'http://127.0.0.1:1234/v1');
  assert.throws(() => config({LOCAL_LLM_URL: 'http://127.0.0.1/v1', LOCAL_LLM_MODEL: 'test', LOCAL_LLM_TIMEOUT_MS: 'NaN'}));
});

test('three independent real HTTP calls to fixture; measures replies', async t => {
  const received = [];
  const cfg = await fixture(t, async (req, res) => {
    assert.equal(req.url, '/v1/chat/completions');
    assert.equal(req.method, 'POST');
    let text = ''; for await (const chunk of req) text += chunk;
    received.push(JSON.parse(text));
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({model: 'fixture', choices: [{message: {content: ['Париж', '3600 × 0.85 + 300 = 3360', 'function uniqueStable(values) { return [...new Set(values)]; }'][received.length - 1]}, finish_reason: 'stop'}]}));
  });
  const report = await run(cfg);
  assert.equal(received.length, 3);
  for (const body of received) {assert.equal(body.model, cfg.model); assert.equal(body.messages.length, 1); assert.equal(body.stream, false);}
  assert.ok(report.results.every(r => r.answer && r.elapsedMs >= 0));
  assert.equal(report.results[0].validation, 'Частичная проверка пройдена');
  assert.equal(report.results[1].validation, 'Частичная проверка пройдена');
  assert.equal(cases[2].check, null);
});

for (const [name, status, body] of [['HTTP error', 503, '{}'], ['bad JSON', 200, '{'], ['empty answer', 200, '{"choices":[]}']]) {
  test(name, async t => {
    const cfg = await fixture(t, (req, res) => {res.writeHead(status); res.end(body);});
    await assert.rejects(request(cfg, 'test'));
  });
}

test('redirect is not followed', async t => {
  let followed = false;
  const cfg = await fixture(t, (req, res) => {
    if (req.url === '/destination') followed = true;
    res.writeHead(302, {Location: '/destination'}); res.end();
  });
  await assert.rejects(request(cfg, 'test'));
  assert.equal(followed, false);
});

test('timeout', async t => {
  const cfg = await fixture(t, () => {});
  await assert.rejects(request({...cfg, timeout: 30}, 'test'), {name: 'TimeoutError'});
});

test('calculation check rejects longer numbers', () => {
  for (const answer of ['13360', '33600', '3360.50']) assert.equal(cases[1].check(answer), false);
  for (const answer of ['Итого: 3360 рублей.', '3 360']) assert.equal(cases[1].check(answer), true);
});

test('request errors do not suppress subsequent cases', async t => {
  let count = 0;
  const cfg = await fixture(t, (req, res) => {
    count++;
    if (count === 1) {res.writeHead(503); res.end();}
    else res.end(JSON.stringify({choices: [{message: {content: 'fixture response'}}]}));
  });
  const report = await run(cfg);
  assert.equal(count, 3);
  assert.equal(report.results[0].error, 'HTTP 503');
  assert.ok(report.results[1].answer);
  assert.ok(report.results[2].answer);
  const html = render({...report, results: [{title: 'error', prompt: 'test', error: '<img onerror=alert(1)>', validation: 'Нет ответа'}]});
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('&lt;img'));
});

test('HTML escapes model output and error text', () => {
  const html = render({base: '<script>', model: 'fixture', startedAt: 'now', results: [{title: 'test', prompt: '<img>', answer: '<script>alert(1)</script>', validation: 'manual'}]});
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
});

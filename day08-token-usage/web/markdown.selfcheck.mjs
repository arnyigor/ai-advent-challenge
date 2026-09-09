#!/usr/bin/env node
// Runnable check for the pure markdown functions in app.js (escapeHtml,
// renderInline, renderMarkdown). Not part of pytest — run directly:
//   node day07-context-memory/web/markdown.selfcheck.mjs
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const appJsPath = path.join(path.dirname(fileURLToPath(import.meta.url)), 'app.js');
const src = readFileSync(appJsPath, 'utf8');
const start = src.indexOf('function escapeHtml');
const end = src.indexOf('function createElement');
const {escapeHtml, renderInline, renderMarkdown} = new Function(
  `${src.slice(start, end)}\nreturn {escapeHtml, renderInline, renderMarkdown};`
)();

assert.equal(renderMarkdown('**bold** and *italic* and `code`'),
  '<p><strong>bold</strong> and <em>italic</em> and <code>code</code></p>');

assert.equal(renderMarkdown('<script>alert(1)</script>'),
  '<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>');

assert.equal(renderMarkdown('1. один\n2. два'), '<ol><li>один</li><li>два</li></ol>');
assert.equal(renderMarkdown('- а\n- б'), '<ul><li>а</li><li>б</li></ul>');

assert.equal(
  renderMarkdown('текст\n\n```js\nconst x = 1;\nif (x) { y(); }\n```\n\nпосле'),
  '<p>текст</p><pre><code>const x = 1;\nif (x) { y(); }</code></pre><p>после</p>',
);

assert.equal(renderMarkdown('строка1\nстрока2'), '<p>строка1<br>строка2</p>');

assert.equal(escapeHtml('<b>&"</b>'), '&lt;b&gt;&amp;"&lt;/b&gt;');
assert.equal(renderInline('**a** *b* `c`'), '<strong>a</strong> <em>b</em> <code>c</code>');

assert.equal(renderMarkdown('### Заголовок\nТекст после без пустой строки'),
  '<h5>Заголовок</h5><p>Текст после без пустой строки</p>');
assert.equal(renderMarkdown('# Только заголовок'), '<h3>Только заголовок</h3>');

assert.equal(
  renderMarkdown('Когда что использовать:\n- Процессы — изоляция\n- Потоки — скорость'),
  '<p>Когда что использовать:</p><ul><li>Процессы — изоляция</li><li>Потоки — скорость</li></ul>',
);
assert.equal(renderMarkdown('просто текст без списка'), '<p>просто текст без списка</p>');

console.log('markdown.selfcheck: все проверки прошли');

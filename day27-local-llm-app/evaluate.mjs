import {mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const base = process.env.DAY27_APP_URL;
if (!base || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) throw Error('Задайте DAY27_APP_URL=http://127.0.0.1:<порт приложения>');
const cases = [
  {mode: 'shorten', text: 'В четверг, 8 октября, в 15:00 состоится встреча команды. Она будет проходить в переговорной №3. Просим всех участников заранее прочитать отчёт и подготовить по два вопроса. Если вы не сможете прийти, сообщите Анне до среды, 7 октября, 18:00.'},
  {mode: 'clarify', text: 'Перед отправкой заявки необходимо, после того как заполнены поля, которые помечены звёздочкой, проверить правильность электронной почты и, если она правильная, нажать кнопку подтверждения, после чего дождаться письма.'},
  {mode: 'tasks', text: 'Иван отправит отчёт к пятнице. Анна проверит таблицу до четверга. Команда обсудила новый дизайн, решение пока не принято.'},
];
const report = {startedAt: new Date().toISOString(), app: base, results: []};
for (const item of cases) {
  const response = await fetch(`${base}/api/transform`, {method: 'POST', redirect: 'error', signal: AbortSignal.timeout(180000), headers: {'Content-Type': 'application/json'}, body: JSON.stringify(item)});
  const result = await response.json();
  report.results.push({...item, httpStatus: response.status, ...result});
  console.log(item.mode, JSON.stringify(result));
  if (item.mode === 'tasks' && response.ok) {
    const message = 'Сделай одной строкой, сохрани исполнителей и сроки.';
    const refined = await fetch(`${base}/api/refine`, {method: 'POST', redirect: 'error', signal: AbortSignal.timeout(180000), headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...item, history: [{role: 'user', content: 'Выполни выбранную обработку исходного текста.'}, {role: 'assistant', content: result.answer}], message})});
    const data = await refined.json(); report.results.push({...item, message, httpStatus: refined.status, ...data}); console.log('refine', JSON.stringify(data));
  }
}
const dir = new URL('./results/', import.meta.url); await mkdir(dir, {recursive:true});
const file = new URL(`cpu-run-${report.startedAt.replace(/[:.]/g, '-')}.json`, dir);
await writeFile(file, JSON.stringify(report, null, 2)); console.log(fileURLToPath(file));
if (report.results.some(r => r.httpStatus !== 200 || !r.answer)) process.exitCode = 1;

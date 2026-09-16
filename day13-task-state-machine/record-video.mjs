#!/usr/bin/env node
// Deterministic browser walkthrough recorded with Chrome CDP and ffmpeg.
import {spawn,spawnSync} from 'node:child_process';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync,realpathSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const dayDir=path.dirname(fileURLToPath(import.meta.url));
const rootDir=path.resolve(dayDir,'..');
const framesDir=mkdtempSync(path.join(os.tmpdir(),'day13-frames-'));
const chromeDir=mkdtempSync(path.join(os.tmpdir(),'day13-chrome-'));
const dataDir=mkdtempSync(path.join(os.tmpdir(),'day13-data-'));
const output=process.argv.includes('--out')?path.resolve(process.argv[process.argv.indexOf('--out')+1]):path.join(rootDir,'ChallengeVideos','day13-demo.mp4');
mkdirSync(path.dirname(output),{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function freePort(){return new Promise((resolve,reject)=>{const socket=net.createServer();socket.once('error',reject);socket.listen(0,'127.0.0.1',()=>{const port=socket.address().port;socket.close(()=>resolve(port));});});}
const port=await freePort(),cdpPort=await freePort();
const chromePath=process.env.CHROME_PATH||path.join(process.env.ProgramFiles||'','Google','Chrome','Application','chrome.exe');
const server=spawn(process.env.PYTHON_PATH||'python',['-c',`from web_server import create_server;s=create_server(port=${port},directory=${JSON.stringify(dataDir)});print(s.server_port,flush=True);s.serve_forever()`],{cwd:dayDir,stdio:'ignore'});
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${cdpPort}`,'--no-sandbox',`--user-data-dir=${chromeDir}`,'--disable-gpu','--window-size=1440,1000','--hide-scrollbars','about:blank'],{stdio:'ignore'});
let socket,recording=true,frame=0,callId=0;
const pending=new Map();
async function waitJson(url){for(let i=0;i<100;i++){try{const response=await fetch(url);if(response.ok)return response.json();}catch{}await sleep(250);}throw new Error(`Не дождался ${url}`);}
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++callId;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const result=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);return result.result.value;}
async function camera(){while(recording){const {data}=await cdp('Page.captureScreenshot',{format:'png',optimizeForSpeed:true});writeFileSync(path.join(framesDir,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));await sleep(125);}}
function caption(title,detail=''){return `(() => {let box=document.getElementById('video-caption');if(!box){box=document.createElement('div');box.id='video-caption';box.style.cssText='position:fixed;top:0;left:0;right:0;z-index:9999;padding:11px 24px 13px;background:#040a15f5;border-bottom:2px solid #79a7ff;text-align:center;font-family:Segoe UI;color:white';box.innerHTML='<b></b><span></span>';box.querySelector('b').style.cssText='display:block;color:#ffd36b;font-size:21px';box.querySelector('span').style.cssText='display:block;margin-top:3px;font-size:15px;color:#dbe7ff';document.body.append(box);document.querySelector('main').style.paddingTop='105px';}box.querySelector('b').textContent=${JSON.stringify(title)};box.querySelector('span').textContent=${JSON.stringify(detail)};})()`;}
function setValue(id,value){return `(() => {const node=document.getElementById(${JSON.stringify(id)});node.value=${JSON.stringify(value)};node.dispatchEvent(new Event('input',{bubbles:true}));})()`;}
function focus(ids=[]){return `(() => {document.querySelectorAll('.video-focus').forEach(x=>{x.classList.remove('video-focus');x.style.removeProperty('outline');x.style.removeProperty('box-shadow')});for(const id of ${JSON.stringify(ids)}){const x=document.getElementById(id);if(x){x.classList.add('video-focus');x.style.outline='3px solid #ffd36b';x.style.boxShadow='0 0 25px #ffd36b88';}}})()`;}
async function scene(title,detail='',action=null,ids=[],ms=3000){if(action)await evaluate(action);await evaluate(caption(title,detail));await evaluate(focus(ids));await sleep(ms);}
async function waitStatus(prefix){for(let i=0;i<600;i++){const value=await evaluate("document.getElementById('status').textContent");if(value.startsWith(prefix))return value;if(value.startsWith('Ошибка:'))throw new Error(value);await sleep(150);}throw new Error(`Статус ${prefix} не появился`);}
async function click(id,expected){await evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);return waitStatus(expected);}
function cleanup(target,prefix){const resolved=realpathSync(target),temp=realpathSync(os.tmpdir());if(path.dirname(resolved)!==temp||!path.basename(resolved).startsWith(prefix))throw new Error('Небезопасный временный путь');rmSync(resolved,{recursive:true,force:true});}
async function main(){await waitJson(`http://127.0.0.1:${cdpPort}/json`);const pages=await waitJson(`http://127.0.0.1:${cdpPort}/json`);socket=new WebSocket(pages.find(item=>item.type==='page').webSocketDebuggerUrl);await new Promise(resolve=>socket.onopen=resolve);socket.onmessage=event=>{const data=JSON.parse(event.data);if(!data.id||!pending.has(data.id))return;const callback=pending.get(data.id);pending.delete(data.id);data.error?callback.reject(new Error(data.error.message)):callback.resolve(data.result);};await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/`});await sleep(1000);const cameraPromise=camera();
  await scene('Что демонстрируем','Автомат всегда хранит: этап, текущий шаг и единственное ожидаемое действие.',null,['stage','step','expected'],4200);
  await scene('Создаём задачу','Исходная цель вводится один раз и дальше хранится в SQLite.',"document.getElementById('create').click()",['objective','task-id'],3200);await waitStatus('Задача создана');
  await scene('Начальное состояние: planning','Шаг — составить план. Перейти дальше можно только действием approve_plan.',null,['stage','step','expected'],4200);
  await evaluate("document.getElementById('compare').scrollIntoView({block:'center'})");await scene('Одинаковая задача — две реальные модели','DeepSeek V4 Flash и GPT-OSS 20B через Wormsoft получают один снимок planning.',"document.getElementById('compare').click()",['compare'],2200);await waitStatus('Сравнение готово');
  await scene('Сравниваем ответы и время','Ответы показаны рядом. Важно: состояние автомата осталось planning.',null,['model-results','comparison-meta'],6000);
  await evaluate("document.querySelector('.use-result').click();document.querySelector('.action-card').scrollIntoView({block:'center'})");await scene('Выбираем результат DeepSeek','Ответ перенесён в результат шага, но переход ещё не выполнен.',null,['result','stage','expected'],3600);
  await scene('Защита от неверного перехода','Пробуем перескочить этап. Внизу автомат сообщает: ожидается approve_plan.',"document.getElementById('wrong').click()",['expected','status'],3400);await waitStatus('Ошибка: Ожидается');
  await scene('Пауза на planning','Этап и ожидаемое действие не пропали — изменился только статус на ПАУЗА.',"document.getElementById('pause').click()",['stage','expected','paused','pause-reason'],3800);await waitStatus('Задача поставлена');
  await scene('Продолжаем planning','После resume возвращаемся ровно к тому же шагу. Цель заново не вводим.',"document.getElementById('resume').click()",['stage','step','expected'],3600);await waitStatus('Продолжаю');
  await scene('Фиксируем выбранный результат planning','Кнопка отправит ожидаемое действие approve_plan; только теперь изменится этап.',null,['result','expected'],3200);
  await scene('Переход planning → execution','План сохранён, активен execution, теперь ожидается complete_execution.',"document.getElementById('advance').click()",['stage','expected','artifacts'],4200);await waitStatus('План сохранён');
  await scene('Пауза на execution','Состояние уже находится в базе: цель, этап execution и утверждённый план.',"document.getElementById('pause').click()",['paused','artifacts'],3400);await waitStatus('Задача поставлена');
  await evaluate(setValue('objective',''));await evaluate("current=null;document.getElementById('stage').textContent='—';document.getElementById('step').textContent='—';document.getElementById('expected').textContent='—';document.getElementById('paused').textContent='—';document.getElementById('artifacts').textContent='{}';document.getElementById('history').replaceChildren()");await scene('Имитируем закрытие приложения','Экран очищен. Оставляем только task_id — повторного описания цели нет.',null,['task-id','objective','stage','artifacts'],4000);
  await scene('Загружаем только по task_id','Автомат восстановил цель, execution, ожидаемое действие и сохранённый план.',"document.getElementById('load').click()",['objective','stage','expected','artifacts'],4700);await waitStatus('Состояние восстановлено');
  await scene('Продолжаем после перезапуска','Resume снимает паузу. Повторять исходную задачу и план не потребовалось.',"document.getElementById('resume').click()",['paused','stage','expected'],3800);await waitStatus('Продолжаю');
  await evaluate(setValue('result','Экспорт PDF реализован, файл сформирован'));await scene('Фиксируем результат execution','Результат реализации добавляется к артефактам задачи.',null,['result'],2800);
  await scene('Переход execution → validation','Теперь автомат ожидает approve_validation — проверку результата.',"document.getElementById('advance').click()",['stage','expected','artifacts'],4200);await waitStatus('Результат сохранён');
  await scene('Пауза работает и на validation','Текущий этап не меняется, проверку можно продолжить позже.',"document.getElementById('pause').click()",['stage','paused','expected'],3200);await waitStatus('Задача поставлена');
  await scene('Возвращаемся к проверке','После resume ожидаемое действие по-прежнему approve_validation.',"document.getElementById('resume').click()",['stage','paused','expected'],3200);await waitStatus('Продолжаю');
  await evaluate(setValue('result','PDF открыт: структура, текст и страницы корректны'));await scene('Фиксируем результат validation','Сохраняем не просто флаг, а понятный отчёт о выполненной проверке.',null,['result'],3000);
  await scene('Переход validation → done','Все обязательные этапы пройдены. Ожидаемого действия больше нет.',"document.getElementById('advance').click()",['stage','expected','artifacts'],4400);await waitStatus('Проверка принята');
  await evaluate("document.getElementById('history').scrollIntoView({block:'center'})");await scene('Итоговый журнал','Внизу видна вся история: создание, паузы, продолжения и три разрешённых перехода.',null,['history'],5200);recording=false;await cameraPromise;
  const encoded=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-framerate','8','-i',path.join(framesDir,'f%05d.png'),'-vf','fps=24,scale=trunc(iw/2)*2:trunc(ih/2)*2','-c:v','libx264','-pix_fmt','yuv420p','-crf','23',output],{stdio:'inherit'});if(encoded.status!==0)throw new Error('ffmpeg завершился с ошибкой');console.log(`Видео: ${output}`);
}
try{await main();}finally{recording=false;try{socket?.close();}catch{}try{chrome.kill();}catch{}try{server.kill();}catch{}cleanup(framesDir,'day13-frames-');cleanup(chromeDir,'day13-chrome-');cleanup(dataDir,'day13-data-');}

#!/usr/bin/env node
// Deterministic Day 14 browser demo recorded through Chrome CDP and ffmpeg.
import {spawn,spawnSync} from 'node:child_process';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync,realpathSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const dayDir=path.dirname(fileURLToPath(import.meta.url)),rootDir=path.resolve(dayDir,'..');
const framesDir=mkdtempSync(path.join(os.tmpdir(),'day14-frames-')),chromeDir=mkdtempSync(path.join(os.tmpdir(),'day14-chrome-'));
const output=process.argv.includes('--out')?path.resolve(process.argv[process.argv.indexOf('--out')+1]):path.join(rootDir,'ChallengeVideos','day14-demo.mp4');
mkdirSync(path.dirname(output),{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function freePort(){return new Promise((resolve,reject)=>{const server=net.createServer();server.once('error',reject);server.listen(0,'127.0.0.1',()=>{const port=server.address().port;server.close(()=>resolve(port));});});}
const port=await freePort(),cdpPort=await freePort();
const chromePath=process.env.CHROME_PATH||path.join(process.env.ProgramFiles||'','Google','Chrome','Application','chrome.exe');
const server=spawn(process.env.PYTHON_PATH||'python',['web_server.py','--port',String(port)],{cwd:dayDir,stdio:'ignore'});
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${cdpPort}`,'--no-sandbox',`--user-data-dir=${chromeDir}`,'--disable-gpu','--window-size=1440,1000','--hide-scrollbars','about:blank'],{stdio:'ignore'});
let socket,recording=true,frame=0,callId=0;const pending=new Map();
async function waitJson(url){for(let i=0;i<100;i++){try{const response=await fetch(url);if(response.ok)return response.json();}catch{}await sleep(250);}throw new Error(`Не дождался ${url}`);}
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++callId;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const result=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);return result.result.value;}
async function camera(){while(recording){const {data}=await cdp('Page.captureScreenshot',{format:'png',optimizeForSpeed:true});writeFileSync(path.join(framesDir,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));await sleep(125);}}
function caption(title,detail){return `(()=>{let box=document.getElementById('video-caption');if(!box){box=document.createElement('div');box.id='video-caption';box.style.cssText='position:fixed;top:0;left:0;right:0;z-index:9999;padding:10px 22px 12px;background:#030a10f5;border-bottom:2px solid #72b7ff;text-align:center;font-family:Segoe UI;color:white';box.innerHTML='<b></b><span></span>';box.querySelector('b').style.cssText='display:block;color:#ffd26a;font-size:21px';box.querySelector('span').style.cssText='display:block;font-size:15px;color:#d7e7f4';document.body.append(box);document.querySelector('main').style.paddingTop='104px'}box.querySelector('b').textContent=${JSON.stringify(title)};box.querySelector('span').textContent=${JSON.stringify(detail)};})()`;}
function focus(selector){return `(()=>{document.querySelectorAll('.video-focus').forEach(x=>{x.classList.remove('video-focus');x.style.removeProperty('outline');x.style.removeProperty('box-shadow')});document.querySelectorAll(${JSON.stringify(selector)}).forEach(x=>{x.classList.add('video-focus');x.style.outline='3px solid #ffd26a';x.style.boxShadow='0 0 24px #ffd26a77'})})()`;}
async function scene(title,detail,action,selector,ms=3500){if(action)await evaluate(action);await evaluate(caption(title,detail));await evaluate(focus(selector));await sleep(ms);}
async function waitText(id,text){for(let i=0;i<600;i++){if((await evaluate(`document.getElementById(${JSON.stringify(id)}).textContent`)).includes(text))return;const status=await evaluate("document.getElementById('status').textContent");if(status.startsWith('Ошибка:'))throw new Error(status);await sleep(100);}throw new Error(`Не появился текст ${text}`);}
async function installCursor(){await evaluate(`(()=>{const cursor=document.createElement('div');cursor.id='demo-cursor';cursor.style.cssText='position:fixed;z-index:10001;width:22px;height:22px;border:3px solid #fff;border-radius:50%;background:#72b7ff88;box-shadow:0 0 12px #000;pointer-events:none;left:1080px;top:760px;transition:left .55s ease,top .55s ease,transform .15s ease';document.body.append(cursor)})()`);}
async function moveTo(selector){await evaluate(`(()=>{const node=document.querySelector(${JSON.stringify(selector)}),cursor=document.getElementById('demo-cursor'),box=node.getBoundingClientRect();cursor.style.left=(box.left+box.width/2-11)+'px';cursor.style.top=(box.top+box.height/2-11)+'px'})()`);await sleep(650);}
async function humanClick(selector){await moveTo(selector);await evaluate(`document.getElementById('demo-cursor').style.transform='scale(.65)'`);await sleep(120);await evaluate(`document.querySelector(${JSON.stringify(selector)}).click();document.getElementById('demo-cursor').style.transform='scale(1)'`);await sleep(450);}
async function humanSelect(id,value){await moveTo(`#${id}`);await evaluate(`(()=>{const node=document.getElementById(${JSON.stringify(id)});node.focus();node.value=${JSON.stringify(value)};node.dispatchEvent(new Event('change',{bubbles:true}))})()`);await sleep(900);}
async function humanType(id,value){await moveTo(`#${id}`);await evaluate(`(()=>{const node=document.getElementById(${JSON.stringify(id)});node.focus();node.value='';node.dispatchEvent(new Event('input',{bubbles:true}))})()`);for(const char of value){await evaluate(`(()=>{const node=document.getElementById(${JSON.stringify(id)});node.value+=${JSON.stringify(char)};node.dispatchEvent(new Event('input',{bubbles:true}))})()`);await sleep(28+Math.floor(Math.random()*38));}await sleep(500);}
async function humanScroll(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({behavior:'smooth',block:'center'})`);await sleep(1200);}
function cleanup(target,prefix){const resolved=realpathSync(target),temp=realpathSync(os.tmpdir());if(path.dirname(resolved)!==temp||!path.basename(resolved).startsWith(prefix))throw new Error('Небезопасный временный путь');rmSync(resolved,{recursive:true,force:true});}
async function main(){await waitJson(`http://127.0.0.1:${cdpPort}/json`);const pages=await waitJson(`http://127.0.0.1:${cdpPort}/json`);socket=new WebSocket(pages.find(item=>item.type==='page').webSocketDebuggerUrl);await new Promise(resolve=>socket.onopen=resolve);socket.onmessage=event=>{const data=JSON.parse(event.data);if(!data.id||!pending.has(data.id))return;const callback=pending.get(data.id);pending.delete(data.id);data.error?callback.reject(new Error(data.error.message)):callback.resolve(data.result)};await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/`});await sleep(1000);await installCursor();const cameraPromise=camera();
  await scene('Инварианты живут отдельно от диалога','Четыре типа правил загружены из версионированного invariants.json.','scrollTo(0,0)','.invariant',5200);
  await scene('Выбираем реальную модель','Переключаем ответ с локального режима на Qwen3.8-27B через RouterAI.',null,'#model',1600);await humanSelect('model','routerai');
  await scene('Допустимый запрос','Печатаем обычный запрос вручную — без готового пресета.',null,'#request',1400);await humanType('request','Добавь фильтр поиска в существующий Compose-экран, сохранив текущие слои');await humanClick('#ask');await waitText('decision','РАЗРЕШЕНО');
  await scene('Реальный ответ Qwen','В подписи видны RouterAI и qwen/qwen3.8-27b. Читаем результат перед проверками.',null,'#decision,#response-model,#answer',5200);await humanScroll('#reasoning');
  await scene('Все правила явно учтены','Trace показывает четыре проверки. Только после них ассистент разрешает ответ.',null,'.check.passed',4800);
  await humanScroll('#request');await scene('Переключаем сценарий','Курсором выбираем конфликт архитектуры.',null,"[data-preset=architecture]",1400);await humanClick('[data-preset=architecture]');await sleep(1400);await humanClick('#ask');await waitText('decision','ОТКАЗ');
  await scene('Конфликт с архитектурой','Запрос требует SQL из UI. Сначала читаем объяснение отказа.',null,'#request,#decision,#answer',4200);await humanScroll('#reasoning');
  await scene('Решение заблокировано до генерации','Назван точный инвариант architecture-clean и показан конфликтный фрагмент.',null,'.check.conflict',5000);
  await humanScroll('[data-preset=business]');await scene('Ещё одно переключение','Выбираем конфликт с бизнес-правилом и запускаем проверку.',null,"[data-preset=business]",1400);await humanClick('[data-preset=business]');await sleep(1300);await humanClick('#ask');await waitText('decision','ОТКАЗ');
  await scene('Пароль в открытом виде запрещён','Просматриваем сформированный отказ, а не мгновенно перескакиваем дальше.',null,'#request,#decision,#answer',4300);await humanScroll('#reasoning');
  await scene('Отказ объяснён','Ассистент называет business-no-passwords, цитирует правило и просит изменить запрос.',null,'.check.conflict',5400);
  await scene('Диалог не может отменить контракт','Даже история с «игнорируй ограничения» не влияет на gate: JSON читается заново до каждого ответа.',null,'.check.conflict,#status',5200);
  recording=false;await cameraPromise;const encoded=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-framerate','8','-i',path.join(framesDir,'f%05d.png'),'-vf','fps=24,scale=trunc(iw/2)*2:trunc(ih/2)*2','-c:v','libx264','-pix_fmt','yuv420p','-crf','23',output],{stdio:'inherit'});if(encoded.status!==0)throw new Error('ffmpeg завершился с ошибкой');console.log(`Видео: ${output}`);
}
try{await main();}finally{recording=false;try{socket?.close()}catch{}try{chrome.kill()}catch{}try{server.kill()}catch{}cleanup(framesDir,'day14-frames-');cleanup(chromeDir,'day14-chrome-');}

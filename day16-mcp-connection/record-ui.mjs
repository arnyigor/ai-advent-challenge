// Reproducible recording of the real Day 16 UI. Chrome CDP + ffmpeg, as in Day 15.
import {spawn,spawnSync} from 'node:child_process';
import {existsSync,mkdirSync,mkdtempSync,writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const day=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(day,'..');
const localPython=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const python=process.env.PYTHON_PATH||(existsSync(localPython)?localPython:'python');
const output=path.join(root,'ChallengeVideos','day16-demo.mp4');
mkdirSync(path.dirname(output),{recursive:true});mkdirSync(path.join(day,'video-frames'),{recursive:true});
const frames=mkdtempSync(path.join(day,'video-frames','ui-'));
const profile=mkdtempSync(path.join(os.tmpdir(),'day16-ui-chrome-'));
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const port=await new Promise((resolve,reject)=>{const s=net.createServer();s.on('error',reject);s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
const app=spawn(python,['web_server.py'],{cwd:day,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
let url='',appOutput='',launchError='';
app.stdout.on('data',data=>{appOutput+=data.toString();url=appOutput.match(/http:\/\/127\.0\.0\.1:\d+\//)?.[0]||'';});
app.stderr.on('data',()=>{});app.on('error',error=>{launchError=error.message;});
const chromePath=process.env.CHROME_PATH||path.join(process.env.ProgramFiles||'','Google/Chrome/Application/chrome.exe');
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,'--window-size=1600,1080','--hide-scrollbars','about:blank'],{stdio:'ignore',windowsHide:true});
chrome.on('error',error=>{launchError=error.message;});
let ws,recording=false,job,cameraError,frame=0,nextId=0;
const pending=new Map();
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++nextId;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout: '+method));},15000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.text);return r.result.value;}
async function camera(){while(recording){const start=Date.now();const {data}=await cdp('Page.captureScreenshot',{format:'png'});writeFileSync(path.join(frames,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));await sleep(Math.max(0,200-(Date.now()-start)));}}
async function waitFor(expression){for(let i=0;i<300;i++){if(await evaluate(expression))return;if(await evaluate("document.querySelector('#status.error')!==null"))throw new Error(await evaluate("document.querySelector('#connection-note').textContent"));await sleep(200);}throw new Error('UI timeout: '+expression);}
async function caption(title,detail){await evaluate(`(()=>{let box=document.getElementById('video-caption');if(!box){box=document.createElement('div');box.id='video-caption';box.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99;padding:12px 30px;background:#030a10f5;border-bottom:2px solid #72b7ff;text-align:center;font-family:Segoe UI;color:white';box.innerHTML='<b style="display:block;font-size:23px;color:#ffd26a"></b><span style="font-size:17px;color:#d7e7f4"></span>';document.body.append(box);document.querySelector('main').style.paddingTop='106px'}box.querySelector('b').textContent=${JSON.stringify(title)};box.querySelector('span').textContent=${JSON.stringify(detail)}})()`);}
async function click(selector){const p=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.scrollIntoView({block:'nearest'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',...p});await sleep(180);await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...p});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...p});}
async function select(id){await evaluate(`(()=>{const e=document.querySelector('#server');e.value=${JSON.stringify(id)};e.dispatchEvent(new Event('change',{bubbles:true}));window.scrollTo(0,0)})()`);}
async function search(text){await click('#search');await evaluate("(()=>{const e=document.querySelector('#search');e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));e.focus()})()");for(const letter of text){await cdp('Input.insertText',{text:letter});await sleep(75);}if(await evaluate("document.querySelector('#search').value")!==text)throw new Error('Search input mismatch');}
async function connect(){await click('#connect');await waitFor("document.querySelector('#status').textContent==='Каталог получен'");}
try{
  let pages;
  for(let i=0;i<120;i++){if(launchError)throw new Error(launchError);try{pages=await(await fetch(`http://127.0.0.1:${port}/json`)).json();if(url)break;}catch{}await sleep(250);}
  if(!pages||!url)throw new Error('UI or Chrome did not start');
  ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  ws.onmessage=event=>{const m=JSON.parse(event.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(new Error(m.error.message)):p.resolve(m.result);};
  await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:1080,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url});await waitFor("document.querySelector('#connect')&&!document.querySelector('#connect').disabled");
  await caption('День 16 · Подключаем MCP через интерфейс','Выбираем сервер → получаем инструменты → изучаем их параметры.');
  recording=true;job=camera().catch(error=>{cameraError=error;recording=false;});await sleep(5000);
  await select('demo');await caption('Начнём с понятного примера','Учебный MCP-сервер предоставляет два инструмента: сложение и приветствие.');await sleep(2500);await connect();
  if(await evaluate("document.querySelector('#tool-count').textContent")!=='2')throw new Error('Expected two demo tools');
  await caption('Соединение работает: получено 2 инструмента','Выбран add. Справа видно: для сложения нужны два целых числа — a и b.');await sleep(6000);
  await click('[data-tool="greet"]');await caption('Каждый инструмент описывает свои аргументы','greet принимает обязательный параметр name. Схема получена от MCP-сервера.');await sleep(5000);
  await select('jarvis');await caption('Теперь подключаем ваш настоящий Jarvis','Тот же клиент получает каталог уже существующего MCP-сервера.');await sleep(2500);await connect();
  const count=await evaluate("Number(document.querySelector('#tool-count').textContent)");
  if(count<3||await evaluate("document.querySelector('#server-name').textContent")!=='Jarvis')throw new Error('Jarvis discovery failed');
  await caption('Jarvis ответил · инструментов: '+count,'В каталоге — работа с файлами, поиск, выполнение кода и документы.');await sleep(5000);
  await search('list_directory');await waitFor("document.querySelectorAll('.tool').length===1");await click('[data-tool="list_directory"]');
  await caption('Поиск по каталогу','list_directory показывает содержимое папки. Параметры представлены обычной таблицей.');await sleep(6000);
  await evaluate("document.querySelector('#detail').scrollTo({top:180,behavior:'smooth'})");await caption('Видно, какие данные нужны для вызова','path обязателен; остальные параметры необязательны. Сам инструмент пока не запускаем.');await sleep(5000);
  await click('#detail summary');await evaluate("document.querySelector('#detail').scrollTo({top:10000,behavior:'smooth'})");await caption('Исходная схема тоже доступна','JSON нужен для технической проверки. Основной интерфейс понятен и без него.');await sleep(4000);
  await search('несуществующий_инструмент');await caption('Поиск обрабатывает и пустой результат','Если совпадений нет, интерфейс предлагает изменить запрос.');await sleep(3000);
  await search('rag_search');await click('[data-tool="rag_search"]');await caption('Можно изучать любой инструмент','rag_search ищет фрагменты в индексе документов. Все описания пришли от Jarvis.');await sleep(5000);
  await evaluate("document.querySelector('.journal').scrollIntoView({block:'center',behavior:'smooth'})");await caption('Журнал подтверждает каждый этап','Сервер ответил, каталог получен, сессия закрыта. Список остаётся доступен для просмотра.');await sleep(5000);
  await evaluate("window.scrollTo({top:0,behavior:'smooth'})");await caption('День 16 готов','Рабочее MCP-соединение и каталог инструментов — в интерфейсе предыдущих дней.');await sleep(4000);
  recording=false;await job;if(cameraError)throw cameraError;
  const encoded=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-loglevel','error','-framerate','5','-i',path.join(frames,'f%05d.png'),'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-vf','fps=25,scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2','-c:v','libx264','-preset','veryfast','-threads','2','-profile:v','baseline','-level:v','4.0','-pix_fmt','yuv420p','-crf','20','-c:a','aac','-shortest','-movflags','+faststart',output],{stdio:'inherit',windowsHide:true});
  if(encoded.status!==0)throw new Error('ffmpeg failed');console.log(JSON.stringify({output,frames,count:frame,tools:count}));
}finally{recording=false;if(job)await job;for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('Recording ended'));}ws?.close();chrome.kill();app.kill();}

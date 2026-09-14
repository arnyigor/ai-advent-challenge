#!/usr/bin/env node
// Record a live browser walkthrough of each memory layer and scope boundary.
import {spawn, spawnSync} from 'node:child_process';
import {mkdtempSync, mkdirSync, writeFileSync, rmSync, realpathSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const dayDir=path.dirname(fileURLToPath(import.meta.url));
const rootDir=path.resolve(dayDir,'..');
const framesDir=mkdtempSync(path.join(os.tmpdir(),'day11-frames-'));
const chromeDir=mkdtempSync(path.join(os.tmpdir(),'day11-chrome-'));
function freePort(){return new Promise((resolve,reject)=>{const s=net.createServer();s.once('error',reject);s.listen(0,'127.0.0.1',()=>{const port=s.address().port;s.close(()=>resolve(port));});});}
const port=process.env.DAY11_WEB_PORT?Number(process.env.DAY11_WEB_PORT):await freePort();
const cdpPort=process.env.DAY11_CDP_PORT?Number(process.env.DAY11_CDP_PORT):await freePort();
const chromePath=process.env.CHROME_PATH||path.join(process.env.ProgramFiles||'','Google','Chrome','Application','chrome.exe');
const output=process.argv.includes('--out')?path.resolve(process.argv[process.argv.indexOf('--out')+1]):path.join(rootDir,'ChallengeVideos','day11-demo.mp4');
mkdirSync(path.dirname(output),{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const server=spawn(process.env.PYTHON_PATH||'python',['web_server.py','--port',String(port)],{cwd:dayDir,stdio:'ignore'});
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${cdpPort}`,'--no-sandbox',`--user-data-dir=${chromeDir}`,'--disable-gpu','--window-size=1440,1000','--hide-scrollbars','about:blank'],{stdio:'ignore'});
let socket,recording=true,frame=0,callId=0;
const pending=new Map();
async function waitJson(url){for(let i=0;i<100;i++){try{const response=await fetch(url);if(response.ok)return response.json();}catch{}await sleep(250);}throw new Error(`Не дождался ${url}`);}
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++callId;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const result=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);return result.result.value;}
async function camera(){while(recording){const {data}=await cdp('Page.captureScreenshot',{format:'png',optimizeForSpeed:true});writeFileSync(path.join(framesDir,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));await sleep(125);}}
function caption(text){return `(() => {let e=document.getElementById('video-caption');if(!e){e=document.createElement('div');e.id='video-caption';e.style.cssText='position:fixed;top:0;left:0;right:0;z-index:9999;padding:15px 25px;background:#050a18f2;border-bottom:1px solid #516189;color:#ffe49e;text-align:center;font:700 18px Segoe UI';document.body.append(e);}e.textContent=${JSON.stringify(text)};})()`;}
async function scene(text,action=null,ms=2800){if(action)await evaluate(action);await evaluate(caption(text));await sleep(ms);}
async function waitStatus(prefix){for(let i=0;i<120;i++){const value=await evaluate("document.getElementById('status').textContent");if(value.startsWith(prefix))return;await sleep(250);}throw new Error(`Не дождался статуса: ${prefix}`);}
function setValue(id,value){return `(() => {const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));})()`;}
async function save(layer,key,value,label){
  await evaluate(setValue('layer',layer));await evaluate(setValue('key',key));await evaluate(setValue('value',value));
  await scene(label,"document.getElementById('save').click()",1900);
  await waitStatus('Факт');
}
async function setLayers(layers){
  await evaluate(`(() => {const selected=new Set(${JSON.stringify(layers)});document.querySelectorAll('[data-layer]').forEach(e=>e.checked=selected.has(e.dataset.layer));})()`);
}
function normalized(value){return String(value).normalize('NFKC').toLowerCase().replace(/[\u2010-\u2015\u2212]/g,'-').replace(/\s+/g,' ');}
async function ask(question,label,{contains=[],absent=[]}={}){
  await evaluate(setValue('prompt',question));
  await scene(label,"document.getElementById('ask').click()",550);
  await waitStatus('Ответ:');
  await evaluate("document.querySelector('.workspace').scrollIntoView({block:'start'})");
  const answer=String(await evaluate("[...document.querySelectorAll('.bubble.assistant')].at(-1)?.textContent || ''"));
  const lower=normalized(answer);
  for(const fact of contains){if(!lower.includes(normalized(fact)))throw new Error(`Ответ не содержит ${fact}: ${answer}`);}
  for(const fact of absent){if(lower.includes(normalized(fact)))throw new Error(`Ответ неожиданно содержит ${fact}: ${answer}`);}
  const context=JSON.parse(await evaluate("document.getElementById('context').textContent"));
  await sleep(3000);
  return {answer,context};
}
function comparisonCard(deepseek,wormsoft){return `(() => {
  const box=document.createElement('div');
  box.id='model-comparison';
  box.style.cssText='position:fixed;inset:90px 7% auto 7%;z-index:900;background:#101b32f7;border:2px solid #7aa2ff;border-radius:18px;padding:26px 30px;color:#e8edf7;box-shadow:0 20px 80px #0009;font:16px Segoe UI';
  const title=document.createElement('h2');title.textContent='Один вопрос · Один контекст · Две модели';title.style.cssText='font-size:29px;margin:0 0 18px';box.append(title);
  const columns=document.createElement('div');columns.style.cssText='display:grid;grid-template-columns:1fr 1fr;gap:16px';
  for(const [label,answer] of ${JSON.stringify([['DeepSeek V4 Flash',deepseek],['Wormsoft · GPT-OSS 20B',wormsoft]])}){
    const card=document.createElement('div');card.style.cssText='background:#20304d;border:1px solid #3d5279;border-radius:12px;padding:19px;min-height:150px';
    const name=document.createElement('b');name.textContent=label;name.style.cssText='display:block;color:#a9c5ff;margin-bottom:14px;font-size:18px';
    const body=document.createElement('div');body.textContent=answer;body.style.whiteSpace='pre-wrap';
    card.append(name,body);columns.append(card);
  }
  box.append(columns);document.body.append(box);
})()`;}
function cleanupTemp(target,prefix){
  const resolved=realpathSync(target);
  const temp=realpathSync(os.tmpdir());
  if(path.dirname(resolved)!==temp||!path.basename(resolved).startsWith(prefix))throw new Error('Небезопасный временный путь');
  rmSync(resolved,{recursive:true,force:true});
}
async function main(){
  await waitJson(`http://127.0.0.1:${port}/api/state`);
  const targets=await waitJson(`http://127.0.0.1:${cdpPort}/json`);
  socket=new WebSocket(targets.find(x=>x.type==='page').webSocketDebuggerUrl);
  await new Promise(resolve=>{socket.onopen=resolve;});
  socket.onmessage=event=>{const message=JSON.parse(event.data);if(!message.id||!pending.has(message.id))return;const cb=pending.get(message.id);pending.delete(message.id);message.error?cb.reject(new Error(message.error.message)):cb.resolve(message.result);};
  await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/`});await sleep(1500);
  const runId=`video-${Date.now()}`;
  await evaluate(setValue('user',runId));await evaluate(setValue('session','session-a'));await evaluate(setValue('task','project-a'));
  await evaluate("document.getElementById('load').click()");
  await waitStatus('Загружены');
  const cameraPromise=camera();
  await scene('День 11 · Что меняется, когда агент видит разные слои памяти?',null,2000);
  await save('short','кодовое_слово','Кедр-71','Явная запись: кодовое слово → краткосрочная память сессии');
  await save('working','срок','15 декабря','Явная запись: срок → рабочая память задачи');
  await save('long','стиль_ответа','кратко, одним предложением','Явная запись: стиль → долговременный профиль пользователя');
  const question='Назови кодовое слово проекта, срок и мой стиль ответа. Для неизвестного напиши «нет данных».';
  await evaluate("document.querySelector('.workspace').scrollIntoView({block:'start'})");
  await setLayers([]);
  await ask(question,'Вариант 1/8 · Нет памяти → нет кодового слова, срока и профиля',{absent:['Кедр-71','15 декабря']});
  await setLayers(['short']);
  await ask(question,'Вариант 2/8 · Только краткосрочная → известно кодовое слово',{contains:['Кедр-71'],absent:['15 декабря']});
  await setLayers(['working']);
  await ask(question,'Вариант 3/8 · Только рабочая → известен срок задачи',{contains:['15 декабря'],absent:['Кедр-71']});
  await setLayers(['long']);
  await ask(question,'Вариант 4/8 · Только долговременная → известен стиль ответа',{contains:['кратко'],absent:['Кедр-71','15 декабря']});
  await setLayers(['short','working','long']);
  await ask(question,'Вариант 5/8 · Все слои → агент объединяет три факта',{contains:['Кедр-71','15 декабря','кратко']});
  await evaluate("window.scrollTo({top:0,behavior:'instant'})");
  await evaluate(setValue('session','session-b'));
  await scene('Новая сессия: краткосрочная память пуста, рабочая и профиль остались',"document.getElementById('load').click()",2000);
  await ask(question,'Вариант 6/8 · Новая сессия → срок и стиль без кодового слова',{contains:['15 декабря','кратко'],absent:['Кедр-71']});
  await evaluate("window.scrollTo({top:0,behavior:'instant'})");
  await evaluate(setValue('session','session-c'));
  await evaluate(setValue('task','project-b'));
  await scene('Новая задача и чистая сессия: остался только профиль пользователя',"document.getElementById('load').click()",2000);
  await ask(question,'Вариант 7/8 · Новая задача → остался только стиль',{contains:['кратко'],absent:['Кедр-71','15 декабря']});
  await evaluate("window.scrollTo({top:0,behavior:'instant'})");
  await evaluate(setValue('user',`${runId}-other`));
  await scene('Другой пользователь: ни один из трёх фактов ему не доступен',"document.getElementById('load').click()",2000);
  await ask(question,'Вариант 8/8 · Другой пользователь → нет сохранённых фактов',{absent:['Кедр-71','15 декабря']});
  await evaluate("window.scrollTo({top:0,behavior:'instant'})");
  await evaluate(setValue('user',runId));
  await evaluate(setValue('task','project-a'));
  await evaluate(setValue('session','compare-deepseek'));
  await scene('Сравнение моделей: новая сессия, те же три факта и тот же вопрос',"document.getElementById('load').click()",1700);
  await save('short','кодовое_слово','Кедр-71','Краткосрочный факт для первого прогона');
  await setLayers(['short','working','long']);
  await evaluate(setValue('provider','deepseek'));
  const deepseek=await ask(question,'Модель 1/2 · DeepSeek V4 Flash',{contains:['Кедр-71','15 декабря','кратко']});
  await evaluate("window.scrollTo({top:0,behavior:'instant'})");
  await evaluate(setValue('session','compare-wormsoft'));
  await scene('Вторая чистая сессия с теми же рабочей памятью и профилем',"document.getElementById('load').click()",1700);
  await save('short','кодовое_слово','Кедр-71','Краткосрочный факт для второго прогона');
  await evaluate(setValue('provider','wormsoft'));
  const wormsoft=await ask(question,'Модель 2/2 · Wormsoft GPT-OSS 20B',{contains:['Кедр-71','15 декабря','кратко']});
  if(deepseek.context.system!==wormsoft.context.system||JSON.stringify(deepseek.context.messages)!==JSON.stringify(wormsoft.context.messages)){
    throw new Error('Контекст двух моделей отличается');
  }
  await scene('Сравниваем реальные ответы двух моделей на полностью одинаковый контекст',comparisonCard(deepseek.answer,wormsoft.answer),4400);
  recording=false;await cameraPromise;
  const encoded=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-framerate','8','-i',path.join(framesDir,'f%05d.png'),'-vf','fps=24,scale=trunc(iw/2)*2:trunc(ih/2)*2','-c:v','libx264','-pix_fmt','yuv420p','-crf','23',output],{stdio:'inherit'});
  if(encoded.status!==0)throw new Error('ffmpeg завершился с ошибкой');
  console.log(`Видео: ${output}`);
}
try{await main();}finally{recording=false;try{socket?.close();}catch{}try{chrome.kill();}catch{}try{server.kill();}catch{}cleanupTemp(framesDir,'day11-frames-');cleanupTemp(chromeDir,'day11-chrome-');}

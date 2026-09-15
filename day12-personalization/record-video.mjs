#!/usr/bin/env node
// Live two-model browser walkthrough, recorded with Chrome CDP and ffmpeg.
import {spawn,spawnSync} from 'node:child_process';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync,realpathSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const dayDir=path.dirname(fileURLToPath(import.meta.url));
const rootDir=path.resolve(dayDir,'..');
const framesDir=mkdtempSync(path.join(os.tmpdir(),'day12-frames-'));
const chromeDir=mkdtempSync(path.join(os.tmpdir(),'day12-chrome-'));
const output=process.argv.includes('--out')?path.resolve(process.argv[process.argv.indexOf('--out')+1]):path.join(rootDir,'ChallengeVideos','day12-demo.mp4');
mkdirSync(path.dirname(output),{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function freePort(){return new Promise((resolve,reject)=>{const s=net.createServer();s.once('error',reject);s.listen(0,'127.0.0.1',()=>{const port=s.address().port;s.close(()=>resolve(port));});});}
const port=await freePort(),cdpPort=await freePort();
const chromePath=process.env.CHROME_PATH||path.join(process.env.ProgramFiles||'','Google','Chrome','Application','chrome.exe');
const server=spawn(process.env.PYTHON_PATH||'python',['web_server.py','--port',String(port)],{cwd:dayDir,stdio:'ignore'});
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${cdpPort}`,'--no-sandbox',`--user-data-dir=${chromeDir}`,'--disable-gpu','--window-size=1440,1000','--hide-scrollbars','about:blank'],{stdio:'ignore'});
let socket,recording=true,frame=0,callId=0;
const pending=new Map();
async function waitJson(url){for(let i=0;i<100;i++){try{const response=await fetch(url);if(response.ok)return response.json();}catch{}await sleep(250);}throw new Error(`Не дождался ${url}`);}
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++callId;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const result=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);return result.result.value;}
async function camera(){while(recording){const {data}=await cdp('Page.captureScreenshot',{format:'png',optimizeForSpeed:true});writeFileSync(path.join(framesDir,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));await sleep(125);}}
function caption(value){return `(() => {let box=document.getElementById('video-caption');if(!box){box=document.createElement('div');box.id='video-caption';box.style.cssText='position:fixed;top:0;left:0;right:0;z-index:9999;padding:15px 24px;background:#060d20f0;border-bottom:1px solid #729cff;color:#ffe49b;text-align:center;font:700 19px Segoe UI';document.body.append(box);}box.textContent=${JSON.stringify(value)};})()`;}
async function scene(label,action=null,ms=2500){if(action)await evaluate(action);await evaluate(caption(label));await sleep(ms);}
function setValue(id,value){return `(() => {const x=document.getElementById(${JSON.stringify(id)});x.value=${JSON.stringify(value)};x.dispatchEvent(new Event('input',{bubbles:true}));})()`;}
async function waitStatus(prefix){for(let i=0;i<600;i++){const value=await evaluate("document.getElementById('status').textContent");if(value.startsWith(prefix))return;if(value.startsWith('Ошибка:'))throw new Error(value);await sleep(250);}throw new Error(`Статус ${prefix} не появился`);}
async function setUser(value){await evaluate("window.scrollTo({top:0,behavior:'instant'})");await evaluate(setValue('user',value));await scene(`Открываем профиль пользователя ${value}`,"document.getElementById('load').click()",1300);await waitStatus('Профиль');}
async function saveProfile(name,{address,style,format,constraints,trigger,roles}){for(const [key,value] of Object.entries({address,style,format,constraints,trigger,roles}))await evaluate(setValue(key,value));await scene(`Пользователь ${name} сохраняет свои правила`,"document.getElementById('save').click()",1700);await waitStatus('Профиль');}
async function saveMemory(){await evaluate("document.getElementById('memory-save').click()");await waitStatus('Факт задачи');}
async function ask(text,model,label,expected){await evaluate("document.querySelector('.workspace').scrollIntoView({block:'start'})");await evaluate(setValue('provider',model));await evaluate(setValue('prompt',text));await scene(label,"document.getElementById('ask').click()",1100);await waitStatus(expected);const answer=await evaluate("document.getElementById('answer').textContent");const context=JSON.parse(await evaluate("document.getElementById('context').textContent"));await sleep(2000);return {answer,context};}
function comparisonCard(title,entries){return `(() => {document.getElementById('model-comparison')?.remove();const box=document.createElement('div');box.id='model-comparison';box.style.cssText='position:fixed;inset:80px 5% auto 5%;max-height:78vh;overflow:auto;z-index:900;background:#101c33f8;border:2px solid #8aafff;border-radius:17px;padding:25px;color:#edf3ff;box-shadow:0 20px 80px #000b;font:16px Segoe UI';const h=document.createElement('h2');h.textContent=${JSON.stringify(title)};h.style.cssText='font-size:29px;margin:0 0 17px';box.append(h);const grid=document.createElement('div');grid.style.cssText='display:grid;grid-template-columns:1fr 1fr;gap:15px';for(const [label,answer] of ${JSON.stringify(entries)}){const card=document.createElement('div');card.style.cssText='background:#213451;border-radius:11px;padding:17px;white-space:pre-wrap;font-size:14px;line-height:1.4';const name=document.createElement('b');name.textContent=label;name.style.cssText='display:block;color:#a9c7ff;margin-bottom:12px;font-size:19px';card.append(name,document.createTextNode(answer.length>1100?answer.slice(0,350)+'\n…\n'+answer.slice(-650):answer));grid.append(card);}box.append(grid);document.body.append(box);})()`;}
function cleanup(target,prefix){const resolved=realpathSync(target),temp=realpathSync(os.tmpdir());if(path.dirname(resolved)!==temp||!path.basename(resolved).startsWith(prefix))throw new Error('Небезопасный временный путь');rmSync(resolved,{recursive:true,force:true});}
async function main(){await waitJson(`http://127.0.0.1:${port}/api/profile`);const pages=await waitJson(`http://127.0.0.1:${cdpPort}/json`);socket=new WebSocket(pages.find(x=>x.type==='page').webSocketDebuggerUrl);await new Promise(resolve=>socket.onopen=resolve);socket.onmessage=event=>{const data=JSON.parse(event.data);if(!data.id||!pending.has(data.id))return;const callback=pending.get(data.id);pending.delete(data.id);data.error?callback.reject(new Error(data.error.message)):callback.resolve(data.result);};await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/`});await sleep(1300);
  const suffix=Date.now(),question='Напиши фичу заметок к сроку проекта. Сформулируй решение для меня.';const cameraPromise=camera();await scene('День 11: какие факты помнит агент. День 12: как он отвечает и кого запускает.',null,2500);
  await setUser(`anna-${suffix}`);await saveProfile('Анна',{address:'Анна',style:'кратко и по делу',format:'два коротких пункта',constraints:'упомяни срок проекта',trigger:'напиши фичу',roles:'analyst, developer'});
  await scene('Одинаковый факт памяти: срок = 15 декабря',"document.getElementById('memory-save').click()",1800);await waitStatus('Факт задачи');
  await scene('Профиль автоматически входит в запрос; роли analyst → developer',"document.getElementById('preview').click()",1900);await waitStatus('Профиль включён');
  await evaluate(setValue('session',`anna-deepseek-${suffix}`));const annaDeepseek=await ask(question,'deepseek','Анна · DeepSeek V4 Flash: две роли по её правилу','Роли выполнены');
  await evaluate(setValue('session',`anna-reasoner-${suffix}`));const annaReasoner=await ask(question,'reasoner','Анна · DeepSeek Reasoner: тот же профиль и контекст','Роли выполнены');
  if(annaDeepseek.context.workflow.join(',')!=='analyst,developer'||JSON.stringify(annaDeepseek.context)!==JSON.stringify(annaReasoner.context))throw new Error('Контекст моделей для Анны отличается');
  await scene('Анна: реальные ответы двух моделей на один и тот же профиль',comparisonCard('Анна · analyst → developer',[['DeepSeek V4 Flash',annaDeepseek.answer],['DeepSeek Reasoner',annaReasoner.answer]]),5500);
  await evaluate("document.getElementById('model-comparison')?.remove()");await setUser(`boris-${suffix}`);await saveProfile('Борис',{address:'Борис',style:'подробно и с объяснением',format:'связный абзац',constraints:'упомяни срок проекта',trigger:'',roles:''});
  await scene('Для Бориса сохраняем тот же факт: срок = 15 декабря',"document.getElementById('memory-save').click()",1700);await waitStatus('Факт задачи');
  await evaluate(setValue('session',`boris-deepseek-${suffix}`));const borisDeepseek=await ask(question,'deepseek','Борис · DeepSeek: тот же вопрос, без запуска ролей','Обычный запрос');
  await evaluate(setValue('session',`boris-reasoner-${suffix}`));const borisReasoner=await ask(question,'reasoner','Борис · Reasoner: тот же вопрос и его профиль','Обычный запрос');
  if(borisDeepseek.context.workflow.length||JSON.stringify(borisDeepseek.context)!==JSON.stringify(borisReasoner.context)||borisDeepseek.context.memory_used.working['срок']!=='15 декабря'||annaDeepseek.context.memory_used.working['срок']!=='15 декабря')throw new Error('Сравнение профилей некорректно');
  await scene('Борис: обе модели отвечают без сценария ролей',comparisonCard('Борис · обычный запрос',[['DeepSeek V4 Flash',borisDeepseek.answer],['DeepSeek Reasoner',borisReasoner.answer]]),5500);
  await scene('Один факт и один вопрос. Пользователь задаёт стиль и порядок ролей.',null,2700);recording=false;await cameraPromise;
  const encoded=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-framerate','8','-i',path.join(framesDir,'f%05d.png'),'-vf','fps=24,scale=trunc(iw/2)*2:trunc(ih/2)*2','-c:v','libx264','-pix_fmt','yuv420p','-crf','23',output],{stdio:'inherit'});if(encoded.status!==0)throw new Error('ffmpeg завершился с ошибкой');console.log(`Видео: ${output}`);
}
try{await main();}finally{recording=false;try{socket?.close();}catch{}try{chrome.kill();}catch{}try{server.kill();}catch{}cleanup(framesDir,'day12-frames-');cleanup(chromeDir,'day12-chrome-');}

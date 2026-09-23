import {spawn,spawnSync} from 'node:child_process';
import {copyFileSync,existsSync,mkdirSync,mkdtempSync,writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const day=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(day,'..');
const localPython=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const python=process.env.PYTHON_PATH||(existsSync(localPython)?localPython:'python');
const resetMode=process.env.DAY18_VIDEO_MODE==='reset';
const output=path.join(root,'ChallengeVideos',resetMode?'day18-reset-demo.mp4':'day18-local-schedule-demo.mp4');
mkdirSync(path.dirname(output),{recursive:true});mkdirSync(path.join(day,'video-frames'),{recursive:true});
const frames=mkdtempSync(path.join(day,'video-frames','ui-'));
const profile=mkdtempSync(path.join(os.tmpdir(),'day18-chrome-'));
const db=path.join(mkdtempSync(path.join(os.tmpdir(),'day18-db-')),'feed.sqlite3');
const seed=process.env.DAY18_VIDEO_SEED_DB;
if(seed){if(!existsSync(seed))throw Error('DAY18_VIDEO_SEED_DB does not exist');copyFileSync(seed,db);}
if(seed){const prep=spawnSync(python,['worker.py','collect'],{cwd:day,windowsHide:true,env:{...process.env,DAY18_DB_PATH:db,PYTHONUTF8:'1'},encoding:'utf8'});if(prep.status!==0)throw Error('RSS preflight failed: '+prep.stderr);}
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const port=await new Promise((resolve,reject)=>{const s=net.createServer();s.on('error',reject);s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
const app=spawn(python,resetMode?['web_server.py']:['web_server.py','--demo-schedule','--collect-seconds','6','--digest-seconds',seed?'45':'14'],{cwd:day,windowsHide:true,env:{...process.env,DAY18_DB_PATH:db,...(seed||resetMode?{}:{DAY18_SIMULATE_PROVIDER_FAILURES:'1'}),PYTHONUTF8:'1'}});
let url='',appOutput='',launchError='';
app.stdout.on('data',data=>{appOutput+=data.toString();url=appOutput.match(/http:\/\/127\.0\.0\.1:\d+\//)?.[0]||'';});
app.stderr.on('data',data=>{launchError+=data.toString();});app.on('error',e=>{launchError=e.message;});
const chromePath=process.env.CHROME_PATH||path.join(process.env.ProgramFiles||'','Google/Chrome/Application/chrome.exe');
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,'--window-size=1600,1080','--hide-scrollbars','about:blank'],{stdio:'ignore',windowsHide:true});
chrome.on('error',e=>{launchError=e.message;});
let ws,recording=false,job,cameraError,frame=0,nextId=0;
const pending=new Map();
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++nextId;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout '+method));},15000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value;}
async function camera(){while(recording){const start=Date.now();const {data}=await cdp('Page.captureScreenshot',{format:'png'});writeFileSync(path.join(frames,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));await sleep(Math.max(0,200-(Date.now()-start)));}}
async function waitFor(expr){for(let i=0;i<150;i++){if(await evaluate(expr))return;await sleep(200);}throw Error('UI timeout: '+expr);}
async function caption(title,detail){await evaluate(`(()=>{let e=document.getElementById('video-caption');if(!e){e=document.createElement('div');e.id='video-caption';e.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99;padding:13px 35px;background:#041414f2;border-bottom:2px solid #62e3bb;color:white;font-family:Segoe UI';e.innerHTML='<b style="display:block;font-size:22px;color:#62e3bb"></b><span style="font-size:16px"></span>';document.body.append(e);document.querySelector('main').style.paddingTop='100px'}e.querySelector('b').textContent=${JSON.stringify(title)};e.querySelector('span').textContent=${JSON.stringify(detail)}})()`);}
async function focus(selector){await evaluate(`(()=>{document.querySelectorAll('.video-focus').forEach(e=>{e.classList.remove('video-focus');e.style.removeProperty('outline');e.style.removeProperty('box-shadow')});document.querySelectorAll(${JSON.stringify(selector)}).forEach(e=>{e.classList.add('video-focus');e.style.outline='4px solid #ffd26a';e.style.boxShadow='0 0 0 7px #ffd26a33,0 0 30px #ffd26a99'})})()`);}
async function click(selector){const p=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);await evaluate(`(()=>{let c=document.getElementById('video-pointer');if(!c){c=document.createElement('div');c.id='video-pointer';c.style.cssText='position:fixed;z-index:9999;width:22px;height:22px;border:4px solid #ffd26a;border-radius:50%;background:#ffd26a55;pointer-events:none;transform:translate(-50%,-50%)';document.body.append(c)}c.style.left=${p.x}+'px';c.style.top=${p.y}+'px'})()`);await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',...p});await sleep(800);await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...p});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...p});}
try{
 let pages;for(let i=0;i<120;i++){if(launchError)throw Error(launchError);try{pages=await(await fetch(`http://127.0.0.1:${port}/json`)).json();if(url)break;}catch{}await sleep(250);}if(!pages||!url)throw Error('Chrome or UI failed to start');
 ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
 ws.onmessage=event=>{const m=JSON.parse(event.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);};
 await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:1080,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url});await waitFor("document.querySelector('#collect')!==null");
 recording=true;job=camera().catch(e=>{cameraError=e;recording=false;});
 if(resetMode){
  await caption('День 18 · Пустая база','До первого запроса нет статей, загрузок и сводок.');await waitFor("document.querySelector('#count').textContent==='0'");await focus('#count,#downloaded,#new-count');await sleep(3500);
  await caption('Нажимаем «Собрать RSS»','Подсвеченная кнопка загружает настоящий RSS Habr и сохраняет статьи в SQLite.');await focus('#collect');await sleep(1300);await click('#collect');await waitFor("Number(document.querySelector('#count').textContent)>0");await focus('#count,#downloaded,#new-count');await sleep(4000);
  await caption('Что загрузилось','Подсвечены полученные и новые статьи; ниже появился журнал загрузок.');await evaluate("document.querySelector('#runs').scrollIntoView({block:'end',behavior:'smooth'})");await focus('#runs');await sleep(3500);await evaluate("window.scrollTo({top:0,behavior:'smooth'})");await sleep(1000);
  await caption('Нажимаем «Сбросить демо»','Кнопка очищает статьи, журнал загрузок и сводки только этого дня.');await focus('#reset');await sleep(1300);await click('#reset');await waitFor("document.querySelector('#count').textContent==='0'");await focus('#count,#downloaded,#new-count');await sleep(3500);
  await caption('Повторяем загрузку','После сброса та же RSS-лента вновь добавляет статьи как новые.');await focus('#collect');await sleep(1300);await click('#collect');await waitFor("Number(document.querySelector('#count').textContent)>0");await focus('#count,#downloaded,#new-count');await sleep(4000);
 }else{
  await caption('День 18 · Настоящий планировщик',seed?'В демо сбор запускается каждые 6 секунд, сводка — каждые 45 секунд.':'В демо сбор запускается каждые 6 секунд, сводка — через 14 секунд.');await sleep(3000);
  await waitFor("Number(document.querySelector('#count').textContent)>0");const firstRun=await evaluate("document.querySelector('#downloaded').textContent");
  await caption('Первый автоматический сбор',seed?'Уже сохранены настоящий RSS и реальная сводка Gemini 3.5.':'Статьи загружены из настоящего RSS и сохранены в SQLite без нажатия кнопки.');await focus('#collect-schedule,#downloaded,#new-count');await sleep(3500);
  await caption('Второй запуск по расписанию','Следующий сбор происходит автоматически; повторы не увеличивают счётчик.');await waitFor("document.querySelector('#runs').children.length>=2");await focus('#collect-schedule,#new-count');await sleep(3000);
  if(seed){await caption('Очередная сводка запланирована','На экране время следующего запуска; готовая сводка Gemini 3.5 сохранена в SQLite.');}
  else{await caption('Автоматическая сводка','Через 14 секунд запускается цепочка моделей. Их отказы в видео эмулированы.');await waitFor("document.querySelector('#model').textContent==='RSS-резерв'");}
  await sleep(4500);
  await caption('Сохранённый результат','Видны попытки моделей, темы выпуска и выдержки из RSS.');await evaluate("document.querySelector('#summary').scrollIntoView({block:'start',behavior:'smooth'})");await sleep(4500);
  await caption('На VPS интервалы будут другими','Сбор каждые 2 часа, сводка ежедневно; управление через systemd timers.');await sleep(4500);
 }
 recording=false;await job;if(cameraError)throw cameraError;
 const ff=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-loglevel','error','-framerate','5','-i',path.join(frames,'f%05d.png'),'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-vf','fps=25,scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2','-c:v','libx264','-preset','veryfast','-threads','2','-profile:v','baseline','-level:v','4.0','-pix_fmt','yuv420p','-crf','20','-c:a','aac','-shortest','-movflags','+faststart',output],{stdio:'inherit',windowsHide:true});if(ff.status!==0)throw Error('ffmpeg failed');console.log(JSON.stringify({output,frames:frame}));
}finally{recording=false;if(job)await job;for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Recording ended'));}ws?.close();chrome.kill();app.kill();}

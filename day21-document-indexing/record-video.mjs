// Record the real Day 21 dashboard through Chrome DevTools Protocol.
import {spawn,spawnSync} from 'node:child_process';
import {existsSync,mkdirSync,mkdtempSync,writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const day=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(day,'..');
const localPython=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const python=process.env.PYTHON_PATH||(existsSync(localPython)?localPython:'python');
const output=path.join(root,'ChallengeVideos','day21-demo.mp4');
if(!existsSync(path.join(day,'data','indexes','fixed.sqlite3')))throw new Error('Build indexes before recording');
mkdirSync(path.dirname(output),{recursive:true});mkdirSync(path.join(day,'video-frames'),{recursive:true});
const frames=mkdtempSync(path.join(day,'video-frames','ui-')),profile=mkdtempSync(path.join(os.tmpdir(),'day21-chrome-'));
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const port=await new Promise((resolve,reject)=>{const server=net.createServer();server.on('error',reject);server.listen(0,'127.0.0.1',()=>{const value=server.address().port;server.close(()=>resolve(value));});});
const app=spawn(python,['web_server.py'],{cwd:day,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
let appOut='',appError='';app.stdout.on('data',data=>{appOut+=data});app.stderr.on('data',data=>{appError+=data});
const chromePath=process.env.CHROME_PATH||path.join(process.env.ProgramFiles||'','Google/Chrome/Application/chrome.exe');
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,'--window-size=1600,1000','--hide-scrollbars','about:blank'],{stdio:'ignore',windowsHide:true});
let ws,recording=false,cameraJob,frame=0,id=0;const pending=new Map();
function cdp(method,params={}){return new Promise((resolve,reject)=>{const key=++id,timer=setTimeout(()=>{pending.delete(key);reject(new Error(`CDP timeout: ${method}`));},20000);pending.set(key,{resolve,reject,timer});ws.send(JSON.stringify({id:key,method,params}));});}
async function evaluate(expression){const result=await cdp('Runtime.evaluate',{expression,returnByValue:true});if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);return result.result.value;}
async function waitFor(expression,tries=1200){for(let i=0;i<tries;i++){if(await evaluate(expression))return;await sleep(250);}throw new Error(`UI timeout: ${expression}`);}
async function caption(title,detail){await evaluate(`(()=>{let box=document.querySelector('#video-caption');if(!box){box=document.createElement('div');box.id='video-caption';box.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99;padding:10px 28px;background:#020b12f5;border-bottom:2px solid #55dbc1;text-align:center;font-family:Segoe UI;color:white';box.innerHTML='<b style="display:block;font-size:22px;color:#55dbc1"></b><span style="font-size:15px;color:#d7e7f4"></span>';document.body.append(box)}box.querySelector('b').textContent=${JSON.stringify(title)};box.querySelector('span').textContent=${JSON.stringify(detail)}})()`);}
async function point(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'})`);const rect=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`);await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',...rect});await sleep(900);await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...rect});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...rect});}
async function highlight(selector,color='#ffd166',hold=1800){await evaluate(`(()=>{const item=document.querySelector(${JSON.stringify(selector)});item.scrollIntoView({block:'center'});item.style.transition='box-shadow .3s,transform .3s';item.style.boxShadow='0 0 0 4px ${color},0 0 38px ${color}66';item.style.transform='scale(1.015)'})()`);await sleep(hold);await evaluate(`(()=>{const item=document.querySelector(${JSON.stringify(selector)});item.style.boxShadow='';item.style.transform=''})()`);}
async function camera(){const began=Date.now();while(recording){const {data}=await cdp('Page.captureScreenshot',{format:'png'});const target=Math.floor((Date.now()-began)/200);do{writeFileSync(path.join(frames,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));}while(frame<=target);await sleep(90);}}

try{
  let pages,url;for(let i=0;i<160;i++){if(appError)throw new Error(appError);try{pages=await(await fetch(`http://127.0.0.1:${port}/json`)).json();url=appOut.match(/http:\/\/127\.0\.0\.1:\d+\//)?.[0];if(pages&&url)break;}catch{}await sleep(250);}if(!pages||!url)throw new Error('Chrome or server did not start');
  ws=new WebSocket(pages.find(page=>page.type==='page').webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});ws.onmessage=event=>{const message=JSON.parse(event.data),entry=pending.get(message.id);if(!entry)return;pending.delete(message.id);clearTimeout(entry.timer);message.error?entry.reject(new Error(message.error.message)):entry.resolve(message.result)};
  await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url});await waitFor("document.querySelector('#status')?.textContent.includes('Готово')");await evaluate("document.body.style.paddingTop='72px'");
  const warm=await fetch(`${url}api/search`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:'Какой аварийный код у проекта Atlas?'})});
  if(!warm.ok)throw new Error(`Embedding warm-up failed: ${warm.status}`);
  recording=true;cameraJob=camera();
  await caption('1. Добавляем документ Atlas','Нажимаем кнопку и наблюдаем реальные этапы pipeline.');await sleep(1200);await point('#demo-run');
  await waitFor("document.querySelector('#status').textContent.includes('Документ проиндексирован')");await sleep(900);
  await caption('2. Document → chunks → embeddings → SQLite','Подсветка прошла по четырём этапам; справа записан журнал каждого шага.');await highlight('.document-stage','#55dbc1',2800);
  await caption('3. Сравниваем реальные чанки Atlas','Fixed режет окно по размеру; Structure сохраняет разделы Подключение, Безопасность и Диагностика.');await highlight('#fixed-chunks .chunk','#ffad5a',2200);await highlight('#structure-chunks .chunk','#55dbc1',2200);
  await caption('4. Цена структуры видна в цифрах','Structure создаёт больше коротких чанков; fixed — меньше окон одинакового размера.');await highlight('.strategy-grid','#6aa8ff',2800);
  await caption('5. Ищем факт из добавленного документа','Вопрос кодируется той же моделью; выдача строится отдельно по двум SQLite-индексам.');await evaluate("document.querySelector('.search-panel').scrollIntoView({block:'start'})");await point('#search-form button');await waitFor("document.querySelectorAll('.result').length>=6");await highlight('#structure-results .result','#55dbc1',3200);
  await caption('6. Проверяем качество на 13 вопросах','Hit@K и MRR сравнивают стратегии при одинаковом корпусе и embedding-модели.');await highlight('.quality','#ffd166',3200);
  await caption('Готово: результат воспроизводим','42 документа · metadata · 384D embeddings · два локальных SQLite-индекса.');await sleep(3200);
  recording=false;await cameraJob;
  const encoded=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-loglevel','error','-framerate','5','-i',path.join(frames,'f%05d.png'),'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-vf','fps=25,scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2','-map','0:v','-map','1:a','-c:v','libx264','-preset','veryfast','-threads','2','-profile:v','baseline','-level:v','4.0','-pix_fmt','yuv420p','-crf','20','-c:a','aac','-shortest','-movflags','+faststart',output],{stdio:'inherit',windowsHide:true});
  if(encoded.status!==0)throw new Error('ffmpeg failed');console.log(JSON.stringify({output,frames:frame}));
}finally{recording=false;if(cameraJob)await cameraJob;for(const entry of pending.values()){clearTimeout(entry.timer);entry.reject(new Error('Recording ended'))}ws?.close();chrome.kill();app.kill();}

// Record the real local plain-vs-RAG flow with Chrome CDP.
import {spawn,spawnSync} from 'node:child_process';
import {existsSync,mkdirSync,mkdtempSync,writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const day=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(day,'..');
const localPython=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const python=process.env.PYTHON_PATH||(existsSync(localPython)?localPython:'python');
const output=path.join(root,'ChallengeVideos','day22-demo.mp4');
const scratch=path.join(day,'video-frames');mkdirSync(path.dirname(output),{recursive:true});mkdirSync(scratch,{recursive:true});
const frames=mkdtempSync(path.join(scratch,'ui-')),profile=mkdtempSync(path.join(os.tmpdir(),'day22-chrome-'));
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const port=await new Promise((resolve,reject)=>{const server=net.createServer();server.on('error',reject);server.listen(0,'127.0.0.1',()=>{const value=server.address().port;server.close(()=>resolve(value));});});
const app=spawn(python,['web_server.py'],{cwd:day,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
let appOut='',appError='';app.stdout.on('data',data=>{appOut+=data.toString();});app.stderr.on('data',data=>{appError+=data.toString();});app.on('error',error=>{appError=error.message;});
const chromePath=process.env.CHROME_PATH||path.join(process.env.ProgramFiles||'','Google/Chrome/Application/chrome.exe');
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,'--window-size=1600,1000','--hide-scrollbars','about:blank'],{stdio:'ignore',windowsHide:true});
chrome.on('error',error=>{appError=error.message;});
let ws,recording=false,job,frame=0,id=0;const pending=new Map();
function cdp(method,params={}){return new Promise((resolve,reject)=>{const key=++id,timer=setTimeout(()=>{pending.delete(key);reject(new Error(`CDP timeout: ${method}`));},20000);pending.set(key,{resolve,reject,timer});ws.send(JSON.stringify({id:key,method,params}));});}
async function evaluate(expression){const value=await cdp('Runtime.evaluate',{expression,returnByValue:true});if(value.exceptionDetails)throw new Error(value.exceptionDetails.text);return value.result.value;}
async function waitFor(expression,attempts=1600){for(let i=0;i<attempts;i++){if(await evaluate(expression))return;await sleep(250);}throw new Error(`UI timeout: ${expression}`);}
async function caption(title,detail){await evaluate(`(()=>{let box=document.querySelector('#video-caption');if(!box){box=document.createElement('div');box.id='video-caption';box.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99;padding:12px 28px;background:#030b12f5;border-bottom:2px solid #58e1c1;text-align:center;color:white;font-family:Segoe UI';box.innerHTML='<b style="display:block;font-size:23px;color:#58e1c1"></b><span style="font-size:16px;color:#d7e7f4"></span>';document.body.append(box)}box.querySelector('b').textContent=${JSON.stringify(title)};box.querySelector('span').textContent=${JSON.stringify(detail)}})()`);}
async function point(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'})`);const rect=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`);await evaluate(`document.querySelector(${JSON.stringify(selector)}).style.outline='3px solid #ffc65a'`);await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',...rect});await sleep(1200);await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...rect});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...rect});await sleep(500);await evaluate(`document.querySelector(${JSON.stringify(selector)}).style.outline=''`);}
async function camera(){const began=Date.now();while(recording){const {data}=await cdp('Page.captureScreenshot',{format:'png'}),target=Math.floor((Date.now()-began)/200);do{writeFileSync(path.join(frames,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));}while(frame<=target);await sleep(100);}}

try{
  let pages,webUrl;for(let i=0;i<180;i++){if(appError)throw new Error(appError);try{pages=await(await fetch(`http://127.0.0.1:${port}/json`)).json();webUrl=appOut.match(/http:\/\/127\.0\.0\.1:\d+\//)?.[0];if(webUrl)break;}catch{}await sleep(250);}if(!pages||!webUrl)throw new Error('Chrome or web server did not start');
  ws=new WebSocket(pages.find(page=>page.type==='page').webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});ws.onmessage=event=>{const message=JSON.parse(event.data),entry=pending.get(message.id);if(!entry)return;pending.delete(message.id);clearTimeout(entry.timer);message.error?entry.reject(new Error(message.error.message)):entry.resolve(message.result);};
  await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url:webUrl});await waitFor("document.querySelector('#preset')?.options.length===10");await evaluate("document.documentElement.style.scrollPaddingTop='92px';document.body.style.paddingTop='78px'");
  await caption('День 22: первый RAG-запрос','Один вопрос и одна DeepSeek V4 Flash. Отличается только наличие найденного контекста.');recording=true;job=camera();await sleep(5500);
  await caption('Pipeline виден целиком','Вопрос → embedding → vector search → top-4 чанка → контекст + вопрос → LLM.');await sleep(5000);
  await caption('Контрольный вопрос об Atlas','Без RAG модель не видит локальную базу. Затем тот же вопрос получит найденные фрагменты.');await point('#run');const waitStart=frame;
  await waitFor("document.querySelector('#status').textContent.startsWith('Готово:')||document.querySelector('#status').textContent.startsWith('Ошибка:')");const waitEnd=frame;
  const status=await evaluate("document.querySelector('#status').textContent");if(!status.startsWith('Готово:'))throw new Error(status);if(!await evaluate("document.querySelector('#rag-answer').textContent.includes('ORBIT-47')"))throw new Error('RAG answer missed ORBIT-47');
  await caption('Сравнение готово','Слева — ответ без базы. Справа — ответ с ORBIT-47, условием использования и ссылкой [1].');await sleep(8500);
  await evaluate("document.querySelector('#retrieval').scrollIntoView({block:'start'})");await caption('Retrieval trace','Первым найден atlas-handbook.md. Видны cosine score, section и фактический текст чанка.');await sleep(7500);
  await evaluate("document.querySelector('.benchmark').scrollIntoView({block:'start'})");await caption('10 контрольных вопросов','Для каждого заранее зафиксированы ожидаемые факты и документы-источники.');await sleep(7500);
  await evaluate("document.querySelector('#questions').lastElementChild.scrollIntoView({block:'end'})");await caption('Сравнение качества воспроизводимо','Отчёт хранит ответы, полноту ключевых терминов и recall источников для всех 10 вопросов.');await sleep(7000);
  recording=false;await job;
  const fps=5,pre=Math.min(waitStart/fps+3,18),post=Math.max(waitEnd/fps-2,pre);const duration=frame/fps;
  const encoded=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-loglevel','error','-framerate',String(fps),'-i',path.join(frames,'f%05d.png'),'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-filter_complex',`[0:v]trim=start=0:end=${pre.toFixed(2)},setpts=PTS-STARTPTS[v0];[0:v]trim=start=${post.toFixed(2)}:end=${duration.toFixed(2)},setpts=PTS-STARTPTS[v1];[v0][v1]concat=n=2:v=1:a=0,fps=25,scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2[v]`,'-map','[v]','-map','1:a','-c:v','libx264','-preset','veryfast','-threads','2','-profile:v','baseline','-level:v','4.0','-pix_fmt','yuv420p','-crf','20','-c:a','aac','-shortest','-movflags','+faststart',output],{stdio:'inherit',windowsHide:true});
  if(encoded.status!==0)throw new Error('ffmpeg failed');console.log(JSON.stringify({output,frames:frame}));
}finally{recording=false;if(job)await job;for(const entry of pending.values()){clearTimeout(entry.timer);entry.reject(new Error('Recording ended'));}ws?.close();chrome.kill();app.kill();}

// Record the actual local web UI and its MCP pipeline with Chrome CDP.
import {spawn,spawnSync} from 'node:child_process';
import {existsSync,mkdirSync,mkdtempSync,writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const day=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(day,'..');
const localPython=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const python=process.env.PYTHON_PATH||(existsSync(localPython)?localPython:'python');
const output=path.join(root,'ChallengeVideos','day19-demo.mp4');
mkdirSync(path.dirname(output),{recursive:true});mkdirSync(path.join(day,'video-frames'),{recursive:true});
const frames=mkdtempSync(path.join(day,'video-frames','ui-'));
const profile=mkdtempSync(path.join(os.tmpdir(),'day19-chrome-'));
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const port=await new Promise((resolve,reject)=>{const server=net.createServer();server.on('error',reject);server.listen(0,'127.0.0.1',()=>{const value=server.address().port;server.close(()=>resolve(value));});});
const app=spawn(python,['web_server.py'],{cwd:day,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
let url='',appError='';app.stdout.on('data',data=>{url+=data.toString();});app.stderr.on('data',data=>{appError+=data.toString();});app.on('error',error=>{appError=error.message;});
const chromePath=process.env.CHROME_PATH||path.join(process.env.ProgramFiles||'','Google/Chrome/Application/chrome.exe');
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,'--window-size=1600,1000','--hide-scrollbars','about:blank'],{stdio:'ignore',windowsHide:true});
chrome.on('error',error=>{appError=error.message;});
let ws,recording=false,job,frame=0,id=0;const pending=new Map();
function cdp(method,params={}){return new Promise((resolve,reject)=>{const key=++id;const timer=setTimeout(()=>{pending.delete(key);reject(new Error(`CDP timeout: ${method}`));},15000);pending.set(key,{resolve,reject,timer});ws.send(JSON.stringify({id:key,method,params}));});}
async function evaluate(expression){const value=await cdp('Runtime.evaluate',{expression,returnByValue:true});if(value.exceptionDetails)throw new Error(value.exceptionDetails.text);return value.result.value;}
async function waitFor(expression){for(let i=0;i<160;i++){if(await evaluate(expression))return;await sleep(250);}throw new Error(`UI timeout: ${expression}`);}
async function caption(title,detail){await evaluate(`(()=>{let box=document.getElementById('video-caption');if(!box){box=document.createElement('div');box.id='video-caption';box.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99;padding:12px 30px;background:#020c18f5;border-bottom:2px solid #5ad8bf;text-align:center;font-family:Segoe UI;color:white';box.innerHTML='<b style="display:block;font-size:23px;color:#5ad8bf"></b><span style="font-size:16px;color:#d7e7f4"></span>';document.body.append(box)}box.querySelector('b').textContent=${JSON.stringify(title)};box.querySelector('span').textContent=${JSON.stringify(detail)}})()`);}
async function camera(){while(recording){const start=Date.now();const {data}=await cdp('Page.captureScreenshot',{format:'png'});writeFileSync(path.join(frames,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));await sleep(Math.max(0,200-(Date.now()-start)));}}
try{
  let pages,webUrl;
  for(let i=0;i<120;i++){if(appError)throw new Error(appError);try{pages=await(await fetch(`http://127.0.0.1:${port}/json`)).json();webUrl=url.match(/http:\/\/127\.0\.0\.1:\d+\//)?.[0];if(webUrl)break;}catch{}await sleep(250);}
  if(!pages||!webUrl)throw new Error('Chrome or web server did not start');
  ws=new WebSocket(pages.find(page=>page.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  ws.onmessage=event=>{const message=JSON.parse(event.data),entry=pending.get(message.id);if(!entry)return;pending.delete(message.id);clearTimeout(entry.timer);message.error?entry.reject(new Error(message.error.message)):entry.resolve(message.result);};
  await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url:webUrl});await waitFor("document.querySelector('#run')!==null");
  await caption('День 19 · Композиция MCP','Один сервер объявляет search, summarize и saveToFile.');recording=true;job=camera();await sleep(3000);
  await caption('Модель: Gemini 3.5 Flash','Второй инструмент обрабатывает найденные материалы реальным вызовом модели.');await sleep(2500);
  await caption('Один запуск всей цепочки','Клиент откроет одно соединение и последовательно вызовет три инструмента.');
  await evaluate("document.querySelector('#run').click()");await waitFor("document.querySelector('#status').textContent.includes('3 вызова')");
  if(await evaluate("document.querySelectorAll('.call').length")!==3)throw new Error('Expected 3 real MCP calls');
  if(await evaluate("document.querySelector('#model').textContent.includes('gemini-3.5-flash')")!==true)throw new Error('Model call did not succeed');
  await caption('Ответ модели: gemini-3.5-flash','Имя модели показано в интерфейсе и вернулось из summarize.');await sleep(3500);
  await evaluate("document.querySelector('.handoff').scrollIntoView({block:'center'})");await caption('Данные передаются автоматически','3 материала → summarize → модельная сводка → saveToFile.');await sleep(4500);
  await caption('Каталог пришёл от MCP-сервера','Три метода получены через tools/list.');await sleep(2500);
  await evaluate("document.querySelector('#trace').scrollIntoView({block:'start'})");await caption('search → summarize','Элементы из первого ответа переданы аргументом второго вызова.');await sleep(4500);
  await evaluate("document.querySelectorAll('.call')[1].scrollIntoView({block:'start'})");await caption('summarize → saveToFile','Готовая сводка передана третьему инструменту.');await sleep(4500);
  await evaluate("document.querySelector('.result').scrollIntoView({block:'end'})");await caption('Итог сохранён в TXT','Путь и содержимое файла получены из ответа saveToFile.');await sleep(5000);
  recording=false;await job;
  const encoded=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-loglevel','error','-framerate','5','-i',path.join(frames,'f%05d.png'),'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-vf','fps=25,scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2','-c:v','libx264','-preset','veryfast','-threads','2','-profile:v','baseline','-level:v','4.0','-pix_fmt','yuv420p','-crf','20','-c:a','aac','-shortest','-movflags','+faststart',output],{stdio:'inherit',windowsHide:true});
  if(encoded.status!==0)throw new Error('ffmpeg failed');console.log(JSON.stringify({output,frames:frame}));
}finally{recording=false;if(job)await job;for(const entry of pending.values()){clearTimeout(entry.timer);entry.reject(new Error('Recording ended'));}ws?.close();chrome.kill();app.kill();}

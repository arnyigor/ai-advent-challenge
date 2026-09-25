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
const output=path.join(root,'ChallengeVideos','day20-demo.mp4');
mkdirSync(path.dirname(output),{recursive:true});mkdirSync(path.join(day,'video-frames'),{recursive:true});
const frames=mkdtempSync(path.join(day,'video-frames','ui-'));
const profile=mkdtempSync(path.join(os.tmpdir(),'day20-chrome-'));
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
async function waitFor(expression){for(let i=0;i<2400;i++){if(await evaluate(expression))return;await sleep(250);}throw new Error(`UI timeout: ${expression}`);}
async function caption(title,detail){await evaluate(`(()=>{let box=document.getElementById('video-caption');if(!box){box=document.createElement('div');box.id='video-caption';box.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99;padding:12px 30px;background:#020c18f5;border-bottom:2px solid #5ad8bf;text-align:center;font-family:Segoe UI;color:white';box.innerHTML='<b style="display:block;font-size:23px;color:#5ad8bf"></b><span style="font-size:16px;color:#d7e7f4"></span>';document.body.append(box)}box.querySelector('b').textContent=${JSON.stringify(title)};box.querySelector('span').textContent=${JSON.stringify(detail)}})()`);}
async function point(selector){
  await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'})`);
  const rect=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  await evaluate(`(()=>{let p=document.querySelector('#pointer');if(!p){p=document.createElement('div');p.id='pointer';p.style.cssText='position:fixed;width:32px;height:32px;border:4px solid #ffd166;background:#ffd16655;border-radius:50%;z-index:100;pointer-events:none;transform:translate(-50%,-50%)';document.body.append(p)}p.style.left='${rect.x}px';p.style.top='${rect.y}px';document.querySelector(${JSON.stringify(selector)}).style.outline='3px solid #ffd166'})()`);
  await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',...rect});await sleep(1500);
  await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...rect});
  await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...rect});
  await sleep(600);await evaluate(`document.querySelector(${JSON.stringify(selector)}).style.outline='';document.querySelector('#pointer').remove()`);
}
async function typeQuery(text){
  await point('#query');
  await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'a',code:'KeyA',modifiers:2,windowsVirtualKeyCode:65});
  await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:'a',code:'KeyA',modifiers:2,windowsVirtualKeyCode:65});
  await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Backspace',code:'Backspace',windowsVirtualKeyCode:8});
  await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:'Backspace',code:'Backspace',windowsVirtualKeyCode:8});
  for(const textPart of text){await cdp('Input.insertText',{text:textPart});await sleep(160);}
  await sleep(1800);
}
async function camera(){const began=Date.now();while(recording){const {data}=await cdp('Page.captureScreenshot',{format:'png'});const target=Math.floor((Date.now()-began)/200);do{writeFileSync(path.join(frames,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));}while(frame<=target);await sleep(100);}}

try{
  let pages,webUrl;
  for(let i=0;i<120;i++){if(appError)throw new Error(appError);try{pages=await(await fetch(`http://127.0.0.1:${port}/json`)).json();webUrl=url.match(/http:\/\/127\.0\.0\.1:\d+\//)?.[0];if(webUrl)break;}catch{}await sleep(250);}
  if(!pages||!webUrl)throw new Error('Chrome or web server did not start');
  ws=new WebSocket(pages.find(page=>page.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  ws.onmessage=event=>{const message=JSON.parse(event.data),entry=pending.get(message.id);if(!entry)return;pending.delete(message.id);clearTimeout(entry.timer);message.error?entry.reject(new Error(message.error.message)):entry.resolve(message.result);};
  await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url:webUrl});await waitFor("document.querySelector('#run')!==null");
  await evaluate("document.documentElement.style.scrollPaddingTop='95px';document.body.style.paddingTop='80px'");
  await caption('День 20: агент и три MCP-сервера','Gemini 3.5 Flash сама выбирает инструменты. Клиент направляет их вызовы в нужный сервер.');recording=true;job=camera();await sleep(6500);
  await caption('Где работает модель','Gemini вызывается через API после каждого ответа MCP. Имя модели и число обращений появятся на странице.');await sleep(6500);
  await caption('Шаг 1. Вводим запрос MCP','Ищем информацию о MCP в локальных материалах дней 16–18.');await typeQuery('MCP');
  await caption('Шаг 2. Нажимаем «Запустить агента»','Модель получит каталог из трёх MCP-серверов и сама выберет первый инструмент.');await point('#run');
  await caption('Gemini выполняет длинный флоу','После каждого вызова инструмента результат возвращается модели. Ждём завершения всех ходов.');
  const waitStart=frame;
  await waitFor("document.querySelector('#status').textContent.includes('Завершено')||document.querySelector('#status').textContent.includes('Ошибка')");
  const waitEnd=frame;
  const status=await evaluate("document.querySelector('#status').textContent");if(!status.includes('8 вызовов'))throw new Error(`Unexpected model run: ${status}`);
  if(await evaluate("document.querySelectorAll('.call').length")!==8)throw new Error('Expected 8 real MCP calls');
  if(!await evaluate("document.querySelector('#status').textContent.includes('gemini-3.5-flash')"))throw new Error('Model identity missing');
  await caption('Живой запуск завершён','Gemini 3.5 Flash выбрала 8 вызовов MCP на 3 серверах за 9 ходов.');await sleep(7000);
  await evaluate("document.querySelector('#catalog').scrollIntoView({block:'start'})");
  await caption('Каталог инструментов от трёх серверов','Имена knowledge.read и storage.read похожи, но ведут в разные MCP-соединения.');await sleep(6500);
  const explanations=[
    ['1. knowledge.search','Модель выбрала поиск и передала тему MCP. Сервер вернул три ID.'],
    ['2. knowledge.read','Модель решила прочитать документ d16.'],
    ['3. knowledge.read','Модель решила прочитать документ d17.'],
    ['4. knowledge.read','Модель решила прочитать документ d18.'],
    ['5. analysis.summarize','Модель передала три прочитанных документа серверу analysis.'],
    ['6. analysis.verify','Модель запросила проверку сводки и источников.'],
    ['7. storage.save','После успешной проверки модель выбрала запись отчёта на сервере storage.'],
    ['8. storage.read','Модель решила прочитать файл обратно и убедиться, что он сохранён.']
  ];
  for(let i=0;i<8;i++){
    await evaluate(`document.querySelectorAll('.call')[${i}].scrollIntoView({block:'start'})`);
    await caption(...explanations[i]);await sleep(5500);
    if(i===4){await point('.call:nth-of-type(5) summary');await sleep(5000);}
  }
  await evaluate("document.querySelector('.result').scrollIntoView({block:'end'})");
  await caption('Итог: ответ модели и файл на диске','Путь и содержимое TXT показаны после контрольного чтения через storage.read.');await sleep(9000);
  recording=false;await job;
  const encoded=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-loglevel','error','-framerate','5','-i',path.join(frames,'f%05d.png'),'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-filter_complex',`[0:v]trim=start=0:end=${(waitStart/5+5).toFixed(2)},setpts=PTS-STARTPTS[v0];[0:v]trim=start=${(waitEnd/5-3).toFixed(2)},setpts=PTS-STARTPTS[v1];[v0][v1]concat=n=2:v=1:a=0,fps=25,scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2[v]`,'-map','[v]','-map','1:a','-c:v','libx264','-preset','veryfast','-threads','2','-profile:v','baseline','-level:v','4.0','-pix_fmt','yuv420p','-crf','20','-c:a','aac','-shortest','-movflags','+faststart',output],{stdio:'inherit',windowsHide:true});
  if(encoded.status!==0)throw new Error('ffmpeg failed');console.log(JSON.stringify({output,frames:frame}));
}finally{recording=false;if(job)await job;for(const entry of pending.values()){clearTimeout(entry.timer);entry.reject(new Error('Recording ended'));}ws?.close();chrome.kill();app.kill();}

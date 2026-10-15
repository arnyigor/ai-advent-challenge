// Continuous capture of a real day34 run. No replay or substituted model results.
import {spawn} from 'node:child_process';
import {existsSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const DAY=path.dirname(fileURLToPath(import.meta.url));
const OUT=path.join(DAY,'video-frames',`live-${Date.now()}`);mkdirSync(OUT,{recursive:true});
const chromePath=process.env.CHROME_PATH||[process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)'],process.env.LOCALAPPDATA].filter(Boolean).map(p=>path.join(p,'Google','Chrome','Application','chrome.exe')).find(existsSync);
if(!chromePath)throw new Error('Set CHROME_PATH');
const port=Number(process.env.DAY34_CDP_PORT||9234),serverPort=process.env.DAY34_WEB_PORT||8834;
const base=`http://127.0.0.1:${serverPort}`;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${path.join(OUT,'browser')}`,'--disable-extensions','--disable-gpu','--no-first-run','--no-default-browser-check','--window-size=1600,1000','about:blank'],{stdio:'ignore'});
let socket,id=0,recording=false,capturePromise,speed=1,phase='Ввод цели';const pending=new Map(),frames=[];
function cdp(method,params={}){return new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(new Error(`${method} timeout`));},20000);pending.set(n,{resolve,reject,timer});socket.send(JSON.stringify({id:n,method,params}));});}
async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw new Error('Browser script failed: '+r.exceptionDetails.text);return r.result.value;}
async function click(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center',behavior:'smooth'})`);await sleep(700);const point=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',...point});await sleep(300);await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});}
async function banner(text,nextSpeed=1){speed=nextSpeed;phase=text;await evaluate(`document.getElementById('recording-label').textContent=${JSON.stringify(text+(nextSpeed>1?' · ожидание ускорено ×12':' · реальная работа, ×1'))}`);}
async function capture(){while(recording){const timestamp=Date.now(),s=speed,p=phase;const {data}=await cdp('Page.captureScreenshot',{format:'jpeg',quality:88});const file=path.join(OUT,`${String(frames.length).padStart(6,'0')}.jpg`);writeFileSync(file,Buffer.from(data,'base64'));frames.push({file,timestamp,speed:s,phase:p});await sleep(300);}}
async function main(){
 const reset=await fetch(base+'/api/reset',{method:'POST'});if(!reset.ok)throw new Error('reset '+reset.status);
 let targets;for(let i=0;i<40;i++){try{const r=await fetch(`http://127.0.0.1:${port}/json`);if(r.ok){targets=await r.json();break;}}catch{}await sleep(300);}
 if(!targets)throw new Error('Chrome unavailable');socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
 socket.onmessage=e=>{const v=JSON.parse(e.data),p=pending.get(v.id);if(!p)return;pending.delete(v.id);clearTimeout(p.timer);v.error?p.reject(new Error(v.error.message)):p.resolve(v.result);};
 await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url:base});
 const deadline=Date.now()+30000;while(!(await evaluate(`document.querySelectorAll('#scenarios button').length===3`))){if(Date.now()>deadline)throw new Error('bootstrap timeout');await sleep(300);}
 await evaluate(`(()=>{const style=document.createElement('style');style.textContent='html{scroll-behavior:smooth;scroll-padding-top:78px}body{padding-top:54px}main{max-width:1400px}.step pre{font-size:16px;max-height:340px}.step .tool,.step .thought{font-size:17px}.step summary{font-size:16px}.step .n{font-size:18px}textarea{font-size:19px}.answer{font-size:19px}pre.diff{font-size:18px}.step{scroll-margin-top:80px}';document.head.append(style);const b=document.createElement('div');b.id='recording-label';b.style.cssText='position:fixed;top:0;left:0;right:0;padding:14px 24px;background:#172554;color:white;font:20px Segoe UI;z-index:9999';document.body.append(b);const p=document.createElement('div');p.style.cssText='position:fixed;width:18px;height:18px;border:2px solid #2563eb;border-radius:50%;background:#60a5fa55;pointer-events:none;z-index:10000';document.body.append(p);document.addEventListener('mousemove',e=>{p.style.left=(e.clientX-9)+'px';p.style.top=(e.clientY-9)+'px'});})()`);
 await banner('1. Ставим цель: изучить промокоды и обновить документацию');recording=true;capturePromise=capture();await sleep(2500);
 await click('#goal');
 const goal='Найди по проекту реализацию и использования промокодов. Объясни, как они работают, и обнови CHANGELOG в разделе Unreleased по найденному коду.';
 for(const chunk of goal.match(/.{1,5}/gu)){await cdp('Input.insertText',{text:chunk});await sleep(60);}await sleep(3000);
 await banner('2. Запускаем: инструменты выбирает сама модель');await click('#run');await sleep(2000);
 await evaluate(`document.getElementById('trace-panel').scrollIntoView({behavior:'smooth',block:'start'})`);
 let seen=0,lastActivity=Date.now();const until=Date.now()+900000;
 while(Date.now()<until){
  const run=await evaluate('window.currentRun||null');
  if(run){
   const fresh=run.steps.slice(seen);
   for(const step of fresh){
    const index=seen++;lastActivity=Date.now();
    if(step.action==='tool'){
     console.log('Live step',step.n,step.tool,step.error?'ERROR':'OK');
     const verb=step.error?'Ошибка инструмента':({'list_files':'Обнаружены файлы проекта','search_files':'Поиск по нескольким файлам','read_file':'Чтение и анализ содержимого','replace_in_file':'Сохранение точечной правки','write_file':'Запись файла','session_diff':'Проверка сохранённых изменений'}[step.tool]||step.tool);
     await banner(`Шаг ${step.n}. ${verb}: ${step.arguments.path||step.arguments.query||step.tool}`);
     const selector=`#steps .step:nth-child(${index+1})`;
     await click(selector+' summary');
     await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'start',behavior:'smooth'})`);
     await sleep(6500);
     await evaluate(`document.querySelector(${JSON.stringify(selector)}).querySelectorAll('pre').forEach(p=>p.scrollTo({top:p.scrollHeight,behavior:'smooth'}))`);
     await sleep(2000);
    }
   }
   if(run.status!=='running'){
    if(run.status!=='done')throw new Error('Live run failed: '+run.error);
    await banner('3. Задача выполнена: ответ и сохранённые изменения');await evaluate(`document.getElementById('answer-panel').scrollIntoView({block:'start',behavior:'smooth'})`);await sleep(7000);
    await banner('4. Итоговый diff: изменения уже записаны в CHANGELOG.md');await evaluate(`document.getElementById('diff-panel').scrollIntoView({block:'start',behavior:'smooth'})`);await sleep(10000);
    await banner('5. Сброс к эталону позволяет повторить весь процесс');await click('#reset');await sleep(3500);
    recording=false;await capturePromise;
    writeFileSync(path.join(DAY,'evidence','live-browser.json'),JSON.stringify({url:base,captured_at:new Date().toISOString(),kind:'continuous capture of a real live model run; only idle waits accelerated x12',run,frames},null,2));
    console.log('Saved real recording',frames.length,'frames');return;
   }
  }
  if(speed===1&&Date.now()-lastActivity>8000)await banner('Модель анализирует результаты и выбирает следующий инструмент',12);
  await sleep(400);
 }
 throw new Error('Live run timeout');
}
try{await main();}finally{recording=false;if(capturePromise)await capturePromise.catch(()=>{});if(frames.length)writeFileSync(path.join(OUT,'raw-capture.json'),JSON.stringify({frames},null,2));socket?.close();chrome.kill();}

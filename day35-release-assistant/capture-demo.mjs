// Continuous recording of a NEW browser run, adapted from day34/capture-live-demo.mjs.
import {spawn,spawnSync} from 'node:child_process';
import {existsSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {DAY,settings} from './config.mjs';
const cfg=settings(),out=path.join(DAY,'video-frames',String(Date.now()));mkdirSync(out,{recursive:true});
const withChecks=process.env.DAY35_DEMO_CHECKS==='1';
const chromePath=process.env.CHROME_PATH||[process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)'],process.env.LOCALAPPDATA].filter(Boolean).map(p=>path.join(p,'Google','Chrome','Application','chrome.exe')).find(existsSync);
if(!chromePath)throw new Error('Укажите CHROME_PATH');
const cdpPort=Number(process.env.DAY35_CDP_PORT||9235),base=`http://127.0.0.1:${cfg.port}`;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const browser=spawn(chromePath,['--headless=new',`--remote-debugging-port=${cdpPort}`,`--user-data-dir=${path.join(out,'browser')}`,'--no-first-run','--no-default-browser-check','--disable-extensions','--window-size=1600,1000','about:blank'],{stdio:'ignore',windowsHide:true});
let socket,seq=0,recording=false,capturePromise,speed=1,phase='',run;const pending=new Map(),frames=[];
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++seq;const timer=setTimeout(()=>{pending.delete(id);reject(new Error(method+' timeout'));},20000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const result=await cdp('Runtime.evaluate',{expression,returnByValue:true});if(result.exceptionDetails)throw new Error('Browser JS: '+result.exceptionDetails.text);return result.result.value;}
async function click(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'})`);await sleep(400);const point=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});}
async function banner(text,factor=1){phase=text;speed=factor;await evaluate(`document.getElementById('recording-label').textContent=${JSON.stringify(text+(factor>1?' · ожидание ускорено ×'+factor:' · реальная работа'))}`);}
async function capture(){while(recording){const timestamp=Date.now(),factor=speed,label=phase;const {data}=await cdp('Page.captureScreenshot',{format:'jpeg',quality:88});const file=path.join(out,`${String(frames.length).padStart(6,'0')}.jpg`);writeFileSync(file,Buffer.from(data,'base64'));frames.push({file,timestamp,speed:factor,phase:label});await sleep(280);}}
async function section(selector,text,hold=6000){await banner(text);await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'start'})`);await sleep(hold);}
async function main(){
  let targets;
  for(let i=0;i<50;i++){try{const response=await fetch(`http://127.0.0.1:${cdpPort}/json`);if(response.ok){targets=await response.json();break;}}catch{}await sleep(200);}
  if(!targets)throw new Error('Chrome unavailable');
  socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  socket.onmessage=event=>{const v=JSON.parse(event.data),p=pending.get(v.id);if(!p)return;pending.delete(v.id);clearTimeout(p.timer);v.error?p.reject(new Error(v.error.message)):p.resolve(v.result);};
  await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url:base});
  for(let i=0;i<50;i++){if(await evaluate(`document.querySelector('#availability')?.textContent.includes('подключён')`))break;await sleep(200);}
  await evaluate(`(()=>{const b=document.createElement('div');b.id='recording-label';b.style.cssText='position:fixed;top:0;left:0;right:0;padding:13px 24px;background:#123d2e;color:white;font:18px Segoe UI;z-index:10000';document.body.append(b);const style=document.createElement('style');style.textContent='body{padding-top:48px}html{scroll-padding-top:70px}.panel{scroll-margin-top:72px}';document.head.append(style);document.querySelector('#result').hidden=true;window.scrollTo(0,0);})()`);
  recording=true;capturePromise=capture();await banner('1. Реальная задача: подготовить обновление DnsHostsGenerator');await sleep(5000);
  await click('#base');await evaluate(`document.querySelector('#base').select()`);await cdp('Input.insertText',{text:cfg.base});
  await click('#head');await evaluate(`document.querySelector('#head').select()`);await cdp('Input.insertText',{text:cfg.head});
  if(withChecks)await click('#checks');
  await banner('2. Выбираем диапазон и запускаем подготовку обновления');await sleep(4000);await click('#run');await sleep(1800);
  const deadline=Date.now()+cfg.modelTimeout+(withChecks?3*cfg.checkTimeout:0)+60000;let sawGit=false;
  while(Date.now()<deadline){
    run=await evaluate('window.currentRun');
    if(run?.evidence&&!sawGit){sawGit=true;await section('#trace-panel','3. Git: реальные коммиты, изменённые файлы и источники',5000);await banner(withChecks?'Сборки и AI-анализ: ожидание результата':'Модель анализирует изменения и готовит материалы',5);}
    if(run&&run.state!=='running'){if(run.state!=='done'||!run.analysis)throw new Error(run.error||'No live analysis');break;}
    await sleep(500);
  }
  if(!run?.analysis)throw new Error('Live run timeout');
  await section('#trace-panel','4. Ответ модели получен; структура и ID источников проверены',6500);
  await section('#checks-panel',withChecks?'5. Фактические результаты тестов и сборок выбранного SHA':'5. Сборки не запускались: сервис сохраняет честный статус',6500);
  await section('#analysis-panel','6. AI объясняет изменения для пользователей Android и Desktop',8000);
  // Open a real cited source from the first change.
  const sourceId=run.analysis.changes[0].evidence_ids[0];
  await click('#changes .refs a');await banner('7. Проверяем вывод AI по исходному diff '+sourceId);await sleep(8500);
  const shot=await cdp('Page.captureScreenshot',{format:'png'});writeFileSync(path.join(out,'source.png'),Buffer.from(shot.data,'base64'));
  await section('#manual','8. Ручной тест-план: действие, ожидаемый результат, источник',7500);
  await section('#notes-panel','9. Готовый черновик описания обновления и файлы отчёта',8500);
  await click('#copy');await sleep(2500);
  await evaluate(`document.querySelector('#analysis-panel').scrollIntoView({block:'start'})`);await banner('Результат: материалы для реального обновления, без автоматической публикации');await sleep(6000);
  const preview=await cdp('Page.captureScreenshot',{format:'png'});mkdirSync(path.join(DAY,'evidence'),{recursive:true});writeFileSync(path.join(DAY,'evidence','preview.png'),Buffer.from(preview.data,'base64'));
  recording=false;await capturePromise;
  const captureData={at:new Date().toISOString(),kind:'continuous real browser run; only labelled build/model waits accelerated x5',run_id:run.id,model:run.model,frames};
  writeFileSync(path.join(out,'capture.json'),JSON.stringify(captureData,null,2));
  const concat=[];let duration=0;
  for(let i=0;i<frames.length;i++){const dt=(i+1<frames.length?frames[i+1].timestamp-frames[i].timestamp:300)/1000/frames[i].speed;duration+=dt;concat.push(`file '${frames[i].file.replaceAll('\\','/').replaceAll("'","'\\''")}'`,`duration ${dt.toFixed(5)}`);}
  concat.push(`file '${frames.at(-1).file.replaceAll('\\','/')}'`);const concatPath=path.join(out,'concat.txt');writeFileSync(concatPath,concat.join('\n')+'\n');
  const videoDir=path.join(DAY,'..','ChallengeVideos');mkdirSync(videoDir,{recursive:true});const video=path.join(videoDir,'day35-demo.mp4');
  const ffmpeg=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',concatPath,'-vf','fps=25','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',video],{encoding:'utf8',windowsHide:true});
  if(ffmpeg.status!==0)throw new Error('ffmpeg: '+ffmpeg.stderr);
  const probe=spawnSync(process.env.FFPROBE_PATH||'ffprobe',['-v','error','-show_format','-show_streams','-of','json',video],{encoding:'utf8',windowsHide:true});
  if(probe.status!==0)throw new Error('ffprobe failed');
  writeFileSync(path.join(DAY,'evidence','live-video.json'),JSON.stringify({at:captureData.at,kind:captureData.kind,run_id:run.id,model:run.model,frames:frames.length,raw_duration_sec:(frames.at(-1).timestamp-frames[0].timestamp)/1000,encoded_duration_sec:duration,video:'ChallengeVideos/day35-demo.mp4',probe:JSON.parse(probe.stdout)},null,2));
  console.log(JSON.stringify({run_id:run.id,frames:frames.length,video,duration_sec:duration}));
}
try{await main();}finally{recording=false;if(capturePromise)await capturePromise.catch(()=>{});if(frames.length)writeFileSync(path.join(out,'raw-capture.json'),JSON.stringify({frames},null,2));socket?.close();browser.kill();}

#!/usr/bin/env node
// Record the real public, read-only VPS page with visible step highlights.
import {spawn, spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, writeFileSync, rmSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const day=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(day,'..');
const url=process.env.DAY18_PUBLIC_URL || 'http://176.53.175.196:8080/';
const output=path.join(root,'ChallengeVideos','day18-demo.mp4');
mkdirSync(path.dirname(output),{recursive:true});
const frames=mkdtempSync(path.join(os.tmpdir(),'day18-public-frames-'));
const profile=mkdtempSync(path.join(os.tmpdir(),'day18-public-chrome-'));
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const port=await new Promise((resolve,reject)=>{const server=net.createServer();server.once('error',reject);server.listen(0,'127.0.0.1',()=>{const p=server.address().port;server.close(()=>resolve(p));});});
const chromePath=process.env.CHROME_PATH||path.join(process.env.ProgramFiles||'','Google/Chrome/Application/chrome.exe');
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,'--window-size=1600,1000','--hide-scrollbars','about:blank'],{stdio:'ignore',windowsHide:true});
let socket,recording=false,cameraJob,frame=0,callId=0,cameraError;
const pending=new Map();
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++callId;const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout '+method));},15000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const result=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.text);return result.result.value;}
async function waitFor(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await sleep(200);}throw Error('UI timeout '+expression);}
async function camera(){while(recording){const start=Date.now();const {data}=await cdp('Page.captureScreenshot',{format:'png'});writeFileSync(path.join(frames,`f${String(frame++).padStart(5,'0')}.png`),Buffer.from(data,'base64'));await sleep(Math.max(0,200-(Date.now()-start)));}}
async function caption(title,detail){await evaluate(`(()=>{let e=document.getElementById('video-caption');if(!e){e=document.createElement('div');e.id='video-caption';e.style.cssText='position:fixed;top:0;left:0;right:0;z-index:9999;padding:11px 28px 13px;background:#031513f4;border-bottom:3px solid #70e5b7;color:white;font-family:Segoe UI';e.innerHTML='<b></b><span></span>';e.querySelector('b').style.cssText='display:block;color:#ffd26a;font-size:22px';e.querySelector('span').style.cssText='display:block;color:#d6ece4;font-size:15px';document.body.append(e);document.querySelector('main').style.paddingTop='117px'}e.querySelector('b').textContent=${JSON.stringify(title)};e.querySelector('span').textContent=${JSON.stringify(detail)}})()`);}
async function focus(selector){await evaluate(`(()=>{document.querySelectorAll('.video-focus').forEach(e=>{e.classList.remove('video-focus');e.style.removeProperty('outline');e.style.removeProperty('box-shadow')});document.querySelectorAll(${JSON.stringify(selector)}).forEach(e=>{e.classList.add('video-focus');e.style.outline='4px solid #ffd26a';e.style.boxShadow='0 0 0 7px #ffd26a33,0 0 30px #ffd26a99'})})()`);}
async function scroll(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center',behavior:'smooth'})`);await sleep(1000);}
async function click(selector){const p=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)}),r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);await evaluate(`(()=>{let c=document.getElementById('video-pointer');if(!c){c=document.createElement('div');c.id='video-pointer';c.style.cssText='position:fixed;z-index:9999;width:22px;height:22px;border:4px solid #ffd26a;border-radius:50%;background:#ffd26a55;pointer-events:none;transform:translate(-50%,-50%)';document.body.append(c)}c.style.left=${p.x}+'px';c.style.top=${p.y}+'px'})()`);await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',...p});await sleep(700);await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...p});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...p});}
try{
 let pages;for(let i=0;i<100;i++){try{pages=await(await fetch(`http://127.0.0.1:${port}/json`)).json();break;}catch{}await sleep(200);}if(!pages)throw Error('Chrome did not start');
 socket=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
 socket.onmessage=event=>{const m=JSON.parse(event.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);};
 await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url});
 await waitFor("Number(document.querySelector('#articles-count')?.textContent)>0");
 recording=true;cameraJob=camera().catch(error=>{cameraError=error;recording=false;});
 await caption('Публичный адрес · '+url,'Проверяющий открывает страницу без SSH, аккаунта и API-ключей.');await focus('.live,.pipeline');await sleep(4500);
 await caption('Реальные данные из SQLite','Загружены статьи RSS; повторные публикации не добавляются.');await focus('.metrics');await sleep(4500);
 await caption('Расписание на капсуле','Сбор каждые 2 часа, сводка ежедневно в 09:00 по Екатеринбургу.');await focus('.schedule');await sleep(4500);
 await caption('Полная сводка без модели','Видны сохранённые темы, выдержки RSS и ссылки на статьи.');await scroll('.digest-panel');await focus('.digest-panel');await sleep(5000);
 await caption('Публикации и журнал','Справа — ссылки на исходные статьи и результаты запусков.');await focus('.side');await sleep(4000);
 await caption('Нажимаем «Скачать TXT»','Полный текст сводки доступен отдельным файлом.');await scroll('.download');await focus('.download');await sleep(1200);await click('.download');await sleep(3200);
 const response=await fetch(new URL('/digest.txt',url));if(!response.ok)throw Error('TXT download failed');
 await caption('Проверка завершена','Страница только для чтения. MCP получает ту же сводку из SQLite.');await focus('.schedule,.metrics');await evaluate('window.scrollTo({top:0,behavior:"smooth"})');await sleep(4500);
 recording=false;await cameraJob;if(cameraError)throw cameraError;
 const ff=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',['-y','-loglevel','error','-framerate','5','-i',path.join(frames,'f%05d.png'),'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-vf','fps=25,scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2','-c:v','libx264','-preset','veryfast','-threads','2','-profile:v','baseline','-level:v','4.0','-pix_fmt','yuv420p','-crf','20','-c:a','aac','-shortest','-movflags','+faststart',output],{stdio:'inherit',windowsHide:true});if(ff.status!==0)throw Error('ffmpeg failed');
 console.log(JSON.stringify({output,frames:frame,url}));
}finally{
 recording=false;if(cameraJob)await cameraJob;
 for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Recording ended'));}
 socket?.close();chrome.kill();
 for(const dir of [frames,profile]){if(!dir.startsWith(os.tmpdir()+path.sep))throw Error('Unsafe temporary path');rmSync(dir,{recursive:true,force:true});}
}

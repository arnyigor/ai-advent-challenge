// Continuous real browser capture with a live model request.
import {spawn} from 'node:child_process';
import {existsSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const DAY=path.dirname(fileURLToPath(import.meta.url));
const OUT=path.join(DAY,'video-frames',`live-${Date.now()}`);mkdirSync(OUT,{recursive:true});
const chromePath=process.env.CHROME_PATH||[process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)'],process.env.LOCALAPPDATA].filter(Boolean).map(p=>path.join(p,'Google','Chrome','Application','chrome.exe')).find(existsSync);
if(!chromePath)throw new Error('Set CHROME_PATH');
const port=Number(process.env.DAY32_CDP_PORT||9232);
const url=process.env.DAY32_DEMO_URL||`http://127.0.0.1:${process.env.DAY32_WEB_PORT||8797}/`;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${path.join(OUT,'browser')}`,'--disable-gpu','--no-first-run','--no-default-browser-check','--window-size=1600,900','about:blank'],{stdio:'ignore'});
let socket,id=0,recording=false,capturePromise;const pending=new Map(),frames=[];
function cdp(method,params={}){return new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(new Error(`${method} timeout`));},20000);pending.set(n,{resolve,reject,timer});socket.send(JSON.stringify({id:n,method,params}));});}
async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw new Error('Browser script failed');return r.result.value;}
async function waitFor(expression,timeout=180000){const end=Date.now()+timeout;while(Date.now()<end){if(await evaluate(expression))return;await sleep(250);}throw new Error(`Timeout: ${expression}`);}
async function click(selector){const point=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',...point});await sleep(350);await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});}
async function capture(){while(recording){const timestamp=Date.now();const {data}=await cdp('Page.captureScreenshot',{format:'jpeg',quality:88});const file=path.join(OUT,`${String(frames.length).padStart(6,'0')}.jpg`);writeFileSync(file,Buffer.from(data,'base64'));frames.push({file,timestamp});await sleep(220);}}
async function main(){
  let targets;for(let i=0;i<40;i++){try{const r=await fetch(`http://127.0.0.1:${port}/json`);if(r.ok){targets=await r.json();break;}}catch{}await sleep(300);}
  if(!targets)throw new Error('Chrome unavailable');socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  socket.onmessage=e=>{const v=JSON.parse(e.data),p=pending.get(v.id);if(!p)return;pending.delete(v.id);clearTimeout(p.timer);v.error?p.reject(new Error(v.error.message)):p.resolve(v.result);};
  await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:900,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url});await waitFor('window.lastState?.stage === "ready"',15000);
  await evaluate(`(()=>{const p=document.createElement('div');p.style.cssText='position:fixed;width:16px;height:16px;border:2px solid white;border-radius:50%;background:#78dfc488;pointer-events:none;z-index:9999';document.body.append(p);document.addEventListener('mousemove',e=>{p.style.left=(e.clientX-8)+'px';p.style.top=(e.clientY-8)+'px';});})()`);
  recording=true;capturePromise=capture();await sleep(4000);
  console.log('Click: start live pipeline');await click('#start');
  await waitFor('window.lastState?.context');await sleep(7000);
  console.log('Click: RAG sources');await click('[data-tab="rag"]');await sleep(7500);
  await cdp('Input.dispatchMouseEvent',{type:'mouseWheel',x:1250,y:680,deltaX:0,deltaY:390});await sleep(6000);
  await waitFor('window.lastState?.stage === "complete" || window.lastState?.stage === "error"');
  if(await evaluate('window.lastState.stage === "error"'))throw new Error('Live model failed');
  await evaluate('window.scrollTo(0,0)');await sleep(1000);console.log('Click: actual model review');await click('[data-tab="review"]');await sleep(7000);
  const max=await evaluate('document.documentElement.scrollHeight-innerHeight');
  for(let y=450;y<max+450;y+=450){await cdp('Input.dispatchMouseEvent',{type:'mouseWheel',x:1320,y:700,deltaX:0,deltaY:450});await sleep(6500);}
  const state=await evaluate('window.lastState');recording=false;await capturePromise;
  writeFileSync(path.join(DAY,'evidence','live-browser.json'),JSON.stringify({url,captured_at:new Date().toISOString(),kind:'continuous browser recording of real live pipeline',state,frames},null,2));
  console.log(`Saved ${frames.length} continuous browser frames`);
}
try{await main();}finally{recording=false;if(capturePromise)await capturePromise.catch(()=>{});socket?.close();chrome.kill();}

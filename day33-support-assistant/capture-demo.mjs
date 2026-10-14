// Real Chromium UI QA and continuous capture, adapted from day32/capture-demo.mjs.
import {spawn} from 'node:child_process';
import {existsSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const DAY=path.dirname(fileURLToPath(import.meta.url));
const OUT=path.join(DAY,'video-frames',`live-${Date.now()}`);mkdirSync(OUT,{recursive:true});
const chromePath=process.env.CHROME_PATH||[process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)'],process.env.LOCALAPPDATA].filter(Boolean).map(p=>path.join(p,'Google','Chrome','Application','chrome.exe')).find(existsSync);
if(!chromePath)throw new Error('Set CHROME_PATH');
const port=Number(process.env.DAY33_CDP_PORT||9233);
const url=process.env.DAY33_DEMO_URL||'http://127.0.0.1:8833/';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const chrome=spawn(chromePath,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${path.join(OUT,'browser')}`,'--disable-extensions','--disable-gpu','--no-first-run','--no-default-browser-check','--window-size=1440,1000','about:blank'],{stdio:'ignore'});
let socket,id=0,recording=false,capturePromise;const pending=new Map(),frames=[],errors=[];
function cdp(method,params={}){return new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(new Error(`${method} timeout`));},20000);pending.set(n,{resolve,reject,timer});socket.send(JSON.stringify({id:n,method,params}));});}
async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error('Browser script failed: '+JSON.stringify(r.exceptionDetails));return r.result.value;}
async function waitFor(expression,timeout=100000){const end=Date.now()+timeout;while(Date.now()<end){if(await evaluate(expression))return;await sleep(250);}throw new Error(`Timeout: ${expression}`);}
async function click(selector){const point=await evaluate(`(()=>{const n=document.querySelector(${JSON.stringify(selector)});if(!n)throw Error('Missing target');n.scrollIntoView({block:'nearest'});const r=n.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',...point});await sleep(200);await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});}
async function type(selector,text){await click(selector);await cdp('Input.insertText',{text});}
async function shot(name){const {data}=await cdp('Page.captureScreenshot',{format:'png'});writeFileSync(path.join(DAY,'evidence',`${name}.png`),Buffer.from(data,'base64'));}
async function capture(){while(recording){const timestamp=Date.now();const {data}=await cdp('Page.captureScreenshot',{format:'jpeg',quality:85});const file=path.join(OUT,`${String(frames.length).padStart(6,'0')}.jpg`);writeFileSync(file,Buffer.from(data,'base64'));frames.push({file,timestamp});await sleep(240);}}
async function ask(text){const before=await evaluate('window.demoState.answers');await type('#message',text);await sleep(1600);await click('#send');await waitFor(`window.demoState.answers>${before} || !!window.demoState.error`);if(await evaluate('!!window.demoState.error'))throw new Error(await evaluate('window.demoState.error'));await sleep(6500);return await evaluate('window.demoState.lastAnswer');}
async function main(){
 let targets;for(let i=0;i<40;i++){try{const r=await fetch(`http://127.0.0.1:${port}/json`);if(r.ok){targets=await r.json();break;}}catch{}await sleep(300);}
 if(!targets)throw new Error('Chrome unavailable');socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
 socket.onmessage=e=>{const v=JSON.parse(e.data),p=pending.get(v.id);if(v.method==='Runtime.exceptionThrown')errors.push(v.params.exceptionDetails);if(!p)return;pending.delete(v.id);clearTimeout(p.timer);v.error?p.reject(new Error(v.error.message)):p.resolve(v.result);};
 await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url});await waitFor('window.demoState?.ready',25000);
 await shot('product-empty');recording=true;capturePromise=capture();await sleep(3500);
 await click('#add-purchase');await type('[name="name"]','Кофемашина');await type('[name="store"]','Магазин техники');await type('[name="note"]','Чек в папке «Покупки», заказ 1042');await sleep(2500);await shot('purchase-form');await click('#save-purchase');await waitFor('window.demoState.purchaseSaved');await sleep(4000);await shot('product-saved');
 await click('#nav-support');await sleep(4000);await shot('support-ready');
 const first=await ask('Почему не работает авторизация?');await shot('answer-expired');
 await click('.answer-sources summary');await sleep(2500);await click('.citation');await sleep(6000);await shot('source-article');await click('[data-close="article-dialog"]');
 await click('[data-ticket-id="SK-1043"]');await waitFor('window.demoState.context?.ticket.id==="SK-1043"');await sleep(3500);
 const second=await ask('Почему не работает авторизация?');await shot('answer-session');
 await click('.trace summary');await sleep(5000);await shot('mcp-trace');
 const followup=await ask('А cookie удалять?');await shot('follow-up');
 recording=false;await capturePromise;
 // Reload checks persisted real exchanges and purchase; then narrow viewport QA.
 await cdp('Page.reload');await waitFor('window.demoState?.ready',25000);
 if(!await evaluate('document.querySelectorAll(".purchase-card").length===1'))throw new Error('Purchase lost on reload');
 await click('#nav-support');await waitFor('document.querySelectorAll(".message.assistant").length===1');
 await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await sleep(1800);await shot('mobile-support');
 const overflow=await evaluate('document.documentElement.scrollWidth>innerWidth+1');if(overflow)throw new Error('Mobile horizontal overflow');
 await click('#nav-product');await sleep(1200);await shot('mobile-product');
 if(await evaluate('document.documentElement.scrollWidth>innerWidth+1'))throw new Error('Product mobile overflow');
 const checks={purchase_persisted:true,history_persisted:true,mobile_no_overflow:true,js_errors:errors.length};if(errors.length)throw new Error('Browser JS errors');
 writeFileSync(path.join(DAY,'evidence','live-browser.json'),JSON.stringify({url,captured_at:new Date().toISOString(),kind:'continuous browser recording, real public API and LLM responses',checks,answers:[first,second,followup],frames},null,2));
 console.log(`Saved ${frames.length} frames. UI checks passed.`);
}
try{await main();}finally{recording=false;if(capturePromise)await capturePromise.catch(()=>{});socket?.close();chrome.kill();}

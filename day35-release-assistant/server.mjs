import http from 'node:http';
import {readFile,readdir} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {DAY,PROFILE,settings} from './config.mjs';
import {git} from './git.mjs';
import {createRun,runRelease} from './release.mjs';
const ARTIFACTS=new Set(['evidence.json','analysis.json','trace.json','release-notes.md','test-plan.md','report.html']);
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
export function createServer(config=settings()) {
  const runs=new Map();let active=null;
  async function loadRun(id) {
    if(!UUID.test(id))return null;
    if(runs.has(id))return runs.get(id);
    try {const run=JSON.parse(await readFile(path.join(config.runsDir,id,'run.json'),'utf8'));return run;}
    catch {return null;}
  }
  return http.createServer(async(req,res)=>{
    const host=req.headers.host;
    const validHosts=[`127.0.0.1:${config.port}`,`localhost:${config.port}`];
    if(!validHosts.includes(host)){res.writeHead(403);res.end('Forbidden host');return;}
    if(req.headers.origin && !validHosts.map(h=>'http://'+h).includes(req.headers.origin)){res.writeHead(403);res.end('Forbidden origin');return;}
    const url=new URL(req.url,`http://${host}`);
    const send=(code,data,type='application/json; charset=utf-8')=>{
      res.writeHead(code,{'Content-Type':type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'"});
      res.end(type.startsWith('application/json')?JSON.stringify(data):data);
    };
    try {
      if(req.method==='GET'&&url.pathname==='/api/config') {
        let tags=[],repoAvailable=true;
        try {tags=(await git(config.repo,'tag','--sort=-version:refname')).trim().split('\n').filter(Boolean);}
        catch {repoAvailable=false;}
        let latest=null;
        try {
          const entries=await readdir(config.runsDir,{withFileTypes:true});
          const recent=await Promise.all(entries.filter(e=>e.isDirectory()&&UUID.test(e.name)).map(e=>loadRun(e.name)));
          latest=recent.filter(Boolean).sort((a,b)=>(b.events[0]?.at||'').localeCompare(a.events[0]?.at||''))[0]?.id||null;
        } catch {}
        send(200,{profile:PROFILE,base:config.base,head:config.head,provider:config.provider,model:config.model,tags,repoAvailable,latest});return;
      }
      if(req.method==='POST'&&url.pathname==='/api/runs') {
        if(active){send(409,{error:'Другой анализ уже выполняется'});return;}
        if(!req.headers['content-type']?.startsWith('application/json')){send(415,{error:'Ожидается JSON'});return;}
        let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>8192){send(413,{error:'Слишком большой запрос'});return;}}
        let body;try{body=JSON.parse(raw);}catch{send(400,{error:'Невалидный JSON'});return;}
        if(!body||typeof body!=='object'||['base','head','model','provider'].some(k=>typeof body[k]!=='string'||body[k].length>180)||typeof body.runChecks!=='boolean'){
          send(400,{error:'Укажите base, head, provider, model и runChecks'});return;
        }
        if(!['gemini','local','openrouter'].includes(body.provider)){send(400,{error:'Неизвестный провайдер'});return;}
        const run=createRun();runs.set(run.id,run);active=run.id;
        void runRelease({...config,base:body.base,head:body.head,provider:body.provider,model:body.model,runChecks:body.runChecks},run)
          .catch(()=>{run.state='error';run.result_status='incomplete';run.error='Не удалось сохранить результат';})
          .finally(()=>{active=null;});
        send(202,{id:run.id});return;
      }
      const match=url.pathname.match(/^\/api\/runs\/([^/]+)(?:\/artifacts\/([^/]+))?$/);
      if(req.method==='GET'&&match) {
        const run=await loadRun(match[1]);if(!run){send(404,{error:'Запуск не найден'});return;}
        if(!match[2]){send(200,run);return;}
        if(!ARTIFACTS.has(match[2])||!run.artifacts.includes(match[2])){send(404,{error:'Артефакт не найден'});return;}
        const file=await readFile(path.join(config.runsDir,run.id,match[2]),'utf8');
        send(200,file,match[2].endsWith('.html')?'text/html; charset=utf-8':'text/plain; charset=utf-8');return;
      }
      const statics={'/':['index.html','text/html'],'/app.js':['app.js','text/javascript'],'/style.css':['style.css','text/css']};
      if(req.method==='GET'&&statics[url.pathname]) {
        const [file,type]=statics[url.pathname];send(200,await readFile(path.join(DAY,'web',file),'utf8'),type+'; charset=utf-8');return;
      }
      send(404,{error:'Не найдено'});
    } catch {if(!res.headersSent)send(500,{error:'Ошибка сервера; проверьте настройки репозитория'});else res.end();}
  });
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) {
  const cfg=settings();const server=createServer(cfg);
  server.on('error',e=>{console.error('Не удалось запустить сервер:',e.code);process.exitCode=1;});
  server.listen(cfg.port,'127.0.0.1',()=>console.log(`AI Release Assistant: http://127.0.0.1:${cfg.port}`));
}

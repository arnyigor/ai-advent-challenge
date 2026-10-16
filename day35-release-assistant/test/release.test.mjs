import {test,before} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {git,collect,allowed,revision} from '../git.mjs';
import {generate,validateAnalysis} from '../model.mjs';
import {checkDefinitions,resultStatus,runProcess} from '../checks.mjs';
import {runRelease} from '../release.mjs';
import {escapeHtml} from '../report.mjs';
import {createServer} from '../server.mjs';
import http from 'node:http';
import {settings} from '../config.mjs';
let repo,base,head;
before(async()=>{
  repo=await mkdtemp(path.join(tmpdir(),'day35-test-'));
  await git(repo,'init');await git(repo,'config','user.name','Day35 Test');await git(repo,'config','user.email','test@example.test');
  await mkdir(path.join(repo,'.github','workflows'),{recursive:true});
  await writeFile(path.join(repo,'.github','workflows','build-apps.yml'),'name: Build\n');
  await writeFile(path.join(repo,'README.md'),'# Test project\n');await writeFile(path.join(repo,'old.kt'),'val renamed = 10\n');await writeFile(path.join(repo,'feature.kt'),'val value = 1\n');
  await git(repo,'add','.');await git(repo,'commit','-m','Initial');base=(await git(repo,'rev-parse','HEAD')).trim();
  await writeFile(path.join(repo,'feature.kt'),'val value = 2\n');await git(repo,'mv','old.kt','new.kt');
  await writeFile(path.join(repo,'README.md'),'# Updated\n');
  await git(repo,'add','.');await git(repo,'commit','-m','Update feature');head=(await git(repo,'rev-parse','HEAD')).trim();
});
const sample=()=>({changes:[{category:'fixed',title:'Исправление',user_impact:'Описание',evidence_ids:['S1']}],risks:[{severity:'low',scenario:'Проверить',evidence_ids:['S1']}],manual_checks:[{action:'Открыть',expected_result:'Работает',evidence_ids:['S1']}],uncertainties:['Ручные проверки не выполнены'],release_notes:'Описание [S1]'});
test('collector uses exact SHA, includes workflow and detects dirty working tree',async()=>{
  await writeFile(path.join(repo,'untracked.md'),'dirty');const e=await collect({repo,base,head});
  assert.equal(e.base_sha,base);assert.equal(e.head_sha,head);assert.equal(e.commits.length,1);assert.equal(e.working_tree_dirty,true);
  assert.ok(e.sources.some(s=>s.path==='.github/workflows/build-apps.yml'));
  assert.ok(e.sources.some(s=>s.text.includes('+val value = 2')));assert.ok(e.changed_files.some(f=>f.old_path==='old.kt'));
});
test('secret and hidden paths are excluded while workflows are allowed',()=>{
  for(const f of ['secret.properties','app/signing.properties','x/.env','data/file.json','.git/config','foo\\bar.kt','a/../b.kt'])assert.equal(allowed(f),false,f);
  assert.equal(allowed('.github/workflows/build-apps.yml'),true);
  assert.equal(allowed('shared/src/commonMain/kotlin/app/data/Presets.kt'),true);
});
test('invalid and missing refs fail',async()=>{
  await assert.rejects(()=>revision(repo,'--output=x'));await assert.rejects(()=>revision(repo,'HEAD~1'));await assert.rejects(()=>revision(repo,'missing-ref'));
});
test('non-ancestor range is rejected',async()=>{await assert.rejects(()=>collect({repo,base:head,head:base}),/предком/);});
test('empty range contains no changes',async()=>{const e=await collect({repo,base:head,head});assert.equal(e.changed_files.length,0);});
test('context truncation is explicit',async()=>{const e=await collect({repo,base,head,maxContext:40});assert.equal(e.coverage_complete,false);assert.ok(e.truncated_sources.length);});
test('unknown evidence ID and textual citation are rejected',()=>{
  const a=sample();a.changes[0].evidence_ids=['S999'];assert.throws(()=>validateAnalysis(a,{sources:[{id:'S1'}]}),/источник/);
  const b=sample();b.release_notes+=' [S999]';assert.throws(()=>validateAnalysis(b,{sources:[{id:'S1'}]}),/ссылка/);
  const c=sample();c.release_notes+=' [S1, S999]';assert.throws(()=>validateAnalysis(c,{sources:[{id:'S1'}]}),/ссылка/);
});
test('wrong response fields rejected',()=>{const a=sample();a.manual_checks='done';assert.throws(()=>validateAnalysis(a,{sources:[{id:'S1'}]}));});
test('not-run and wrong-SHA checks never become success',()=>{
  const e={head_sha:head,checks:checkDefinitions(head),coverage_complete:true,changed_files:[{}]};
  assert.equal(resultStatus(e,sample()),'incomplete');for(const c of e.checks)c.status='passed';
  assert.equal(resultStatus(e,sample()),'checks_passed_review_needed');e.checks[0].tested_sha='other';assert.equal(resultStatus(e,sample()),'incomplete');
});
test('failed/timeout checks block even with valid AI',()=>{
  const e={head_sha:head,checks:checkDefinitions(head),coverage_complete:true,changed_files:[{}]};e.checks[0].status='failed';assert.equal(resultStatus(e,sample()),'blocked');
  e.checks[0].status='timeout';assert.equal(resultStatus(e,sample()),'blocked');
});
test('model network failure and incomplete answer remain errors',async()=>{
  const cfg={...settings(),provider:'local',model:'test'};
  await assert.rejects(()=>generate({sources:[]},cfg,async()=>{throw new Error('private details');}),/сетевая ошибка/);
  await assert.rejects(()=>generate({sources:[]},cfg,async()=>({ok:true,json:async()=>({choices:[{finish_reason:'length',message:{content:'{}'}}]})})),/незавершённый/);
});
test('invalid JSON rejected and valid JSON accepted through adapter',async()=>{
  const cfg={...settings(),provider:'local',model:'test'};
  const response=text=>async()=>({ok:true,json:async()=>({choices:[{finish_reason:'stop',message:{content:text}}]})});
  await assert.rejects(()=>generate({sources:[]},cfg,response('oops')),/JSON/);
  const result=await generate({sources:[{id:'S1'}]},cfg,response(JSON.stringify(sample())));assert.equal(result.analysis.changes.length,1);
});
test('model refuses nonloopback local endpoint',async()=>{await assert.rejects(()=>generate({}, {...settings(),provider:'local',model:'test',localUrl:'http://example.com/v1'}),/loopback/);});
test('temporary HTTP error retries same model and records attempt',async()=>{
  let calls=0;const events=[];const cfg={...settings(),provider:'local',model:'test'};
  const result=await generate({sources:[{id:'S1'}]},cfg,async(url,request)=>{
    calls++;assert.equal(JSON.parse(request.body).model,'test');
    return calls===1?{status:503,ok:false}:{status:200,ok:true,json:async()=>({choices:[{finish_reason:'stop',message:{content:JSON.stringify(sample())}}]})};
  },(stage,message)=>events.push({stage,message}));
  assert.equal(calls,2);assert.equal(events.length,1);assert.equal(result.model,'local:test');
});
test('process failures and timeout carry correct statuses',async()=>{
  assert.equal((await runProcess(process.execPath,['-e','process.exit(3)'],repo,3000)).status,'failed');
  assert.equal((await runProcess(process.execPath,['-e','setTimeout(()=>{},10000)'],repo,50)).status,'timeout');
});
test('HTML output escapes model data',()=>{assert.equal(escapeHtml('<script>"&'), '&lt;script&gt;&quot;&amp;');assert.equal(escapeHtml('a\n b'),'a&#10; b');});
test('facts-only orchestrator writes real artifacts and keeps incomplete',async()=>{
  const runsDir=await mkdtemp(path.join(tmpdir(),'day35-runs-'));
  const run=await runRelease({repo,base,head,collectOnly:true,runsDir});assert.equal(run.state,'done');assert.equal(run.result_status,'incomplete');assert.equal(run.analysis,null);
  const e=JSON.parse(await readFile(path.join(runsDir,run.id,'evidence.json'),'utf8'));assert.equal(e.head_sha,head);
  assert.ok((await readFile(path.join(runsDir,run.id,'report.html'),'utf8')).includes('Недостаточно'));
});
test('HTTP rejects cross-origin execution and arbitrary artifact paths',async()=>{
  const config={...settings(),port:0,repo,base,head};const server=createServer(config);await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const port=server.address().port;
  config.port=port;
  try {
    const response=await fetch(`http://127.0.0.1:${port}/api/runs`,{method:'POST',headers:{Origin:'https://example.com'}});assert.equal(response.status,403);
    const invalid=await fetch(`http://127.0.0.1:${port}/api/runs/not-a-uuid/artifacts/secret.properties`);assert.equal(invalid.status,404);
  } finally {await new Promise(r=>server.close(r));}
});
test('full HTTP flow calls local model and exposes saved artifacts',async()=>{
  const runsDir=await mkdtemp(path.join(tmpdir(),'day35-http-'));
  let received=null;
  const modelServer=http.createServer(async(req,res)=>{let raw='';for await(const chunk of req)raw+=chunk;received=JSON.parse(raw);
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({choices:[{finish_reason:'stop',message:{content:JSON.stringify(sample())}}]}));});
  await new Promise(r=>modelServer.listen(0,'127.0.0.1',r));
  const config={...settings(),port:0,repo,base,head,runsDir,provider:'local',model:'test',localUrl:`http://127.0.0.1:${modelServer.address().port}/v1`};
  const server=createServer(config);await new Promise(r=>server.listen(0,'127.0.0.1',r));config.port=server.address().port;const url=`http://127.0.0.1:${config.port}`;
  try {
    const started=await fetch(url+'/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base,head,provider:'local',model:'test',runChecks:false})});
    assert.equal(started.status,202);const {id}=await started.json();let run;
    for(let i=0;i<100;i++){run=await(await fetch(url+'/api/runs/'+id)).json();if(run.state!=='running')break;await new Promise(r=>setTimeout(r,100));}
    assert.equal(run.state,'done');assert.equal(run.model,'local:test');assert.equal(run.result_status,'incomplete');assert.ok(received.messages[1].content.includes(head));
    const artifact=await fetch(url+`/api/runs/${id}/artifacts/release-notes.md`);assert.equal(artifact.status,200);assert.ok((await artifact.text()).includes('Описание [S1]'));
    const denied=await fetch(url+`/api/runs/${id}/artifacts/run.json`);assert.equal(denied.status,404);
  } finally {await new Promise(r=>server.close(r));await new Promise(r=>modelServer.close(r));}
});

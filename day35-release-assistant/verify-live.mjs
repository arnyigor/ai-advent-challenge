// Accept a persisted REAL run; publish a portable evidence bundle without local paths.
import {readFile,writeFile,copyFile,mkdir,readdir,stat} from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {DAY,settings} from './config.mjs';
import {validateAnalysis} from './model.mjs';
import {resultStatus} from './checks.mjs';
const id=process.argv[2];
if(!id){console.log('node day35-release-assistant/verify-live.mjs <run-UUID>\nПроверяет реальный сохранённый прогон и сохраняет публичные доказательства.');}
else {
  if(!/^[0-9a-f-]{36}$/.test(id))throw new Error('Invalid run ID');
  const source=path.join(settings().runsDir,id),dest=path.join(DAY,'evidence');
  const run=JSON.parse(await readFile(path.join(source,'run.json'),'utf8'));
  if(run.state!=='done'||!run.analysis||!run.model)throw new Error('Завершённый реальный AI-анализ обязателен');
  validateAnalysis(run.analysis,run.evidence);
  if(resultStatus(run.evidence,run.analysis)!==run.result_status)throw new Error('Неверный итоговый статус');
  const e=run.evidence,manifest=[];let tests={tests:0,failures:0,errors:0,skipped:0};
  async function hash(file,kind) {
    const digest=createHash('sha256');for await(const chunk of createReadStream(file))digest.update(chunk);
    manifest.push({kind,file:path.relative(path.join(source,'checkout'),file).replaceAll('\\','/'),bytes:(await stat(file)).size,sha256:digest.digest('hex')});
  }
  if(e.checks.every(c=>c.status==='passed'&&c.tested_sha===e.head_sha)) {
    const root=path.join(source,'checkout');
    const apkDir=path.join(root,'androidApp/build/outputs/apk/debug');
    for(const name of await readdir(apkDir))if(name.endsWith('.apk'))await hash(path.join(apkDir,name),'android-debug-apk');
    const appDir=path.join(root,'desktopApp/build/compose/binaries/main/app/DnsHostsGenerator');
    if(process.platform==='win32') {
      await hash(path.join(appDir,'DnsHostsGenerator.exe'),'windows-launcher');
      await hash(path.join(appDir,'runtime/bin/server/jvm.dll'),'bundled-jvm');
    }
    const results=path.join(root,'shared/build/test-results/jvmTest');
    for(const name of await readdir(results))if(/^TEST-.*\.xml$/.test(name)) {
      const xml=await readFile(path.join(results,name),'utf8');const suite=xml.match(/<testsuite\s[^>]+>/)?.[0]||'';
      for(const field of Object.keys(tests))tests[field]+=Number(suite.match(new RegExp(`\\b${field}="(\\d+)"`))?.[1]||0);
    }
    if(!tests.tests||tests.failures||tests.errors)throw new Error('Неверный отчёт JVM-тестов');
  }
  await mkdir(dest,{recursive:true});
  const map={'evidence.json':'live-evidence.json','analysis.json':'live-analysis.json','trace.json':'live-trace.json','release-notes.md':'release-notes.md','test-plan.md':'test-plan.md','report.html':'report.html'};
  for(const [from,to]of Object.entries(map))await copyFile(path.join(source,from),path.join(dest,to));
  const summary={at:new Date().toISOString(),run_id:id,model:run.model,result_status:run.result_status,
    base_sha:e.base_sha,head_sha:e.head_sha,commits:e.commits.length,changed_files:e.changed_files.length,sources:e.sources.length,
    coverage_complete:e.coverage_complete,changes:run.analysis.changes.length,manual_checks:run.analysis.manual_checks.length,
    checks:e.checks,jvm_tests:tests,build_artifacts:manifest,
    limitations:['Смысловая точность AI требует просмотра','Desktop проверен только на Windows','Production-подпись и реальные устройства не проверены']};
  await writeFile(path.join(dest,'acceptance.json'),JSON.stringify(summary,null,2),'utf8');
  console.log(JSON.stringify(summary,null,2));
}

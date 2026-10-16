import {spawn,execFile} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {PROFILE} from './config.mjs';
import {git,redact} from './git.mjs';

export function checkDefinitions(sha) {
  return PROFILE.checks.map(c=>({...c,argv:['java','org.gradle.wrapper.GradleWrapperMain',c.task,'--no-daemon','--console=plain'],
    tested_sha:sha,status:'not_run',exit_code:null,duration_ms:0,log_path:null}));
}
// A fixed command per profile. No shell, project config or model-generated commands.
export async function runProcess(executable,args,cwd,timeout) {
  return new Promise(resolve=>{
    let output='',timedOut=false,spawnError=false,finished=false;
    const start=Date.now();
    // Do not inherit cloud credentials into build scripts.
    const inherited=new Set(['PATH','PATHEXT','SYSTEMROOT','WINDIR','COMSPEC','JAVA_HOME','ANDROID_HOME','ANDROID_SDK_ROOT','TEMP','TMP','USERPROFILE','HOME','APPDATA','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMDATA','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE']);
    const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>inherited.has(key.toUpperCase())));
    env.GRADLE_USER_HOME=process.env.DAY35_GRADLE_HOME || path.join(cwd,'.gradle-user');
    const proc=spawn(executable,args,{cwd,env,windowsHide:true,detached:process.platform!=='win32',stdio:['ignore','pipe','pipe']});
    const finish=(code)=>{if(finished)return;finished=true;clearTimeout(timer);resolve({status:timedOut?'timeout':spawnError?'unavailable':code===0?'passed':'failed',exit_code:code,duration_ms:Date.now()-start,output:redact(output)});};
    const append=b=>{if(output.length<1200000) output+=b.toString('utf8').slice(0,1200000-output.length);};
    proc.stdout.on('data',append);proc.stderr.on('data',append);
    proc.on('error',()=>{spawnError=true;finish(null);});
    proc.on('close',finish);
    const timer=setTimeout(()=>{
      timedOut=true;
      if(process.platform==='win32'&&proc.pid)execFile('taskkill',['/PID',String(proc.pid),'/T','/F'],{windowsHide:true},()=>{});
      else {try{process.kill(-proc.pid,'SIGKILL');}catch{proc.kill();}}
    },timeout);
  });
}
export async function runChecks(repo,evidence,runDir,timeout,emit=()=>{}) {
  const checkout=path.join(runDir,'checkout');
  emit('checks','Создаём отдельную копию выбранного SHA для проверок');
  await git(repo,'clone','--no-local','--no-hardlinks','--no-checkout',repo,checkout);
  await git(checkout,'checkout','--detach',evidence.head_sha);
  const testedSha=(await git(checkout,'rev-parse','HEAD')).trim();
  if(testedSha!==evidence.head_sha) throw new Error('SHA checkout не совпадает с head');
  await mkdir(path.join(runDir,'logs'),{recursive:true});
  const java=process.env.JAVA_HOME?path.join(process.env.JAVA_HOME,'bin',process.platform==='win32'?'java.exe':'java'):'java';
  for(const check of evidence.checks) {
    emit('checks',`Проверка: ${check.id}`);
    const args=['-Dorg.gradle.appname=gradlew','-classpath',path.join(checkout,'gradle','wrapper','gradle-wrapper.jar'),'org.gradle.wrapper.GradleWrapperMain',check.task,'--no-daemon','--console=plain'];
    const result=await runProcess(java,args,checkout,timeout);
    const {output,...meta}=result;Object.assign(check,meta,{tested_sha:testedSha,log_path:`logs/${check.id}.log`});
    await writeFile(path.join(runDir,check.log_path),output,'utf8');
    emit('checks',`${check.id}: ${check.status}`);
  }
}
export function resultStatus(evidence,analysis) {
  if(evidence.checks.some(c=>c.required&&['failed','timeout'].includes(c.status)))return 'blocked';
  if(!analysis || !evidence.coverage_complete || !evidence.changed_files.length || !evidence.checks.length ||
    evidence.checks.some(c=>c.required&&(c.status!=='passed'||c.tested_sha!==evidence.head_sha)))return 'incomplete';
  return 'checks_passed_review_needed';
}

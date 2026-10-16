import {mkdir,writeFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
import {settings} from './config.mjs';
import {collect} from './git.mjs';
import {generate} from './model.mjs';
import {checkDefinitions,runChecks,resultStatus} from './checks.mjs';
import {writeReport} from './report.mjs';

export function createRun() {return {id:randomUUID(),state:'running',stage:'starting',events:[],evidence:null,analysis:null,model:null,usage:null,error:null,result_status:'incomplete',artifacts:[]};}
export async function runRelease(options={},run=createRun()) {
  const cfg={...settings(),...options};
  const dir=path.join(cfg.runsDir,run.id);await mkdir(dir,{recursive:true});
  const emit=(stage,message)=>{run.stage=stage;run.events.push({at:new Date().toISOString(),stage,message});};
  try {
    emit('git','Читаем выбранные версии Git');
    run.evidence=await collect(cfg,emit);run.evidence.run_id=run.id;
    run.evidence.checks=checkDefinitions(run.evidence.head_sha);
    await writeFile(path.join(dir,'evidence.json'),JSON.stringify(run.evidence,null,2),'utf8');
    if(cfg.runChecks)await runChecks(cfg.repo,run.evidence,dir,cfg.checkTimeout,emit);
    else emit('checks','Сборки не запрошены: проверки имеют статус not_run');
    if(!run.evidence.changed_files.length)emit('empty','В диапазоне нет изменений');
    else if(cfg.collectOnly)emit('facts','Собраны только факты, AI не запускался');
    else {
      emit('model',`Генерация ${cfg.provider}:${cfg.model||'модель не задана'} · ${run.evidence.sources.length} источников`);
      const result=await generate(run.evidence,cfg,fetch,emit);Object.assign(run,result);
      emit('validation','JSON и ссылки на источники проверены');
    }
    run.stage='saving';
  } catch(error) {
    run.state='error';run.error=error.message?.replaceAll(cfg.repo,'<repo>')||'Ошибка выполнения';
    // Git can include raw argv/paths in errors; expose only a short single-line message.
    if(run.error.startsWith('Command failed:'))run.error='Ошибка Git: проверьте путь к репозиторию и наличие выбранных refs';
    emit('error',run.error);
  }
  run.result_status=run.evidence?resultStatus(run.evidence,run.analysis):'incomplete';
  emit('complete',`Итог: ${run.result_status}`);
  if(run.evidence)run.artifacts=await writeReport(run,dir);
  if(run.state!=='error')run.state='done';
  await writeFile(path.join(dir,'run.json'),JSON.stringify(run,null,2),'utf8');
  return run;
}

import {runRelease} from './release.mjs';
const args=process.argv.slice(2);
if(!args.length || args.includes('--help')) {
  console.log('AI Release Assistant · DnsHostsGenerator\n\nnode cli.mjs --base v1.4.0 --head v1.4.1 [--collect-only] [--run-checks]\nНастройки: DAY35_REPO, DAY35_PROVIDER, DAY35_MODEL.\nИнтерфейс: node server.mjs\nБез --run-checks сборки не выполняются; исходный репозиторий не меняется.');
} else {
  const options={};
  for(let i=0;i<args.length;i++) {
    const key=args[i];
    if(key==='--collect-only')options.collectOnly=true;
    else if(key==='--run-checks')options.runChecks=true;
    else if(['--repo','--base','--head','--provider','--model'].includes(key)&&args[i+1]&&!args[i+1].startsWith('--'))options[key.slice(2)]=args[++i];
    else {console.error('Неизвестный или неполный аргумент:',key);process.exit(2);}
  }
  const run=await runRelease(options);
  console.log(JSON.stringify({id:run.id,state:run.state,status:run.result_status,error:run.error,events:run.events,artifacts:run.artifacts},null,2));
  if(run.state==='error')process.exitCode=1;
}

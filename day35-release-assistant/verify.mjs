import {spawnSync} from 'node:child_process';
import {readdir,mkdir,writeFile,readFile} from 'node:fs/promises';
import path from 'node:path';
import {DAY} from './config.mjs';
const files=[...(await readdir(DAY)).filter(n=>n.endsWith('.mjs')).map(n=>path.join(DAY,n)),path.join(DAY,'web','app.js'),path.join(DAY,'test','release.test.mjs')];
for(const file of files){const p=spawnSync(process.execPath,['--check',file],{stdio:'inherit',windowsHide:true});if(p.status!==0)process.exit(p.status||1);}
const scan=[...files,...(await readdir(DAY)).filter(n=>n.endsWith('.json')||n.endsWith('.md')).map(n=>path.join(DAY,n))];
for(const dir of ['web','evidence'])for(const item of await readdir(path.join(DAY,dir),{withFileTypes:true}).catch(()=>[]))if(item.isFile()&&/\.(md|json|js|html|css)$/.test(item.name))scan.push(path.join(DAY,dir,item.name));
const leaks=[];
for(const file of scan){const text=await readFile(file,'utf8');if(/AIza[\w-]{35}|(?:ghp_|github_pat_)[\w]{30,}|sk-[A-Za-z0-9]{30,}|Bearer\s+[A-Za-z0-9_.-]{30,}/.test(text))leaks.push(path.relative(DAY,file));}
if(leaks.length){console.error('Possible secret in:',leaks.join(', '));process.exit(1);}
console.log(`Secret scan: ${scan.length} authored/evidence files, no keys found`);
const test=spawnSync(process.execPath,['--test',path.join(DAY,'test','release.test.mjs')],{encoding:'utf8',windowsHide:true});
process.stdout.write(test.stdout);process.stderr.write(test.stderr);
await mkdir(path.join(DAY,'evidence'),{recursive:true});
await writeFile(path.join(DAY,'evidence','verification.json'),JSON.stringify({at:new Date().toISOString(),syntax_files:files.map(f=>path.relative(DAY,f)),secret_scan:{files:scan.length,leaks:[]},exit_code:test.status,tests_output:test.stdout},null,2),'utf8');
if(test.status!==0)process.exitCode=test.status||1;

import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import path from 'node:path';
const exec = promisify(execFile);
export async function git(repo, ...args) {
  const result = await exec('git', ['-c','core.quotepath=false','-C',repo,...args], {
    encoding: 'utf8', maxBuffer: 24*1024*1024, timeout: 60000, windowsHide: true,
    env: {...process.env, GIT_TERMINAL_PROMPT:'0', GIT_OPTIONAL_LOCKS:'0'},
  });
  return result.stdout;
}
export function redact(text) {
  return text.replace(/AIza[\w-]{20,}|(?:ghp_|github_pat_)[\w]{15,}|sk-[\w-]{20,}/g, '[REDACTED]');
}
export function allowed(file) {
  if (file.includes('\\') || file.split('/').some(p => p==='..')) return false;
  if (/(?:secret|credential|token|keystore|signing|private[._-]?key|local\.properties|\.env)/i.test(file)) return false;
  if (file.startsWith('.github/workflows/')) return /^\.github\/workflows\/[\w.-]+\.ya?ml$/.test(file);
  if (file.startsWith('data/') || file.split('/').some(p => p.startsWith('.') || ['build','node_modules','vendor'].includes(p))) return false;
  return ['.kt','.kts','.md','.toml','.properties','.xml','.json','.sql'].includes(path.posix.extname(file));
}
export async function revision(repo, ref) {
  if (typeof ref!=='string' || ref.length>160 || !/^[A-Za-z0-9][A-Za-z0-9_./-]*$/.test(ref)) throw new Error('Недопустимый Git ref');
  try { return (await git(repo,'rev-parse','--verify',`${ref}^{commit}`)).trim(); }
  catch { throw new Error(`Git ref не найден: ${ref}`); }
}
async function textBlob(repo, sha, file) {
  const entry = await git(repo,'ls-tree','-z',sha,'--',file);
  if (!entry) return '';
  if (!/^100(?:644|755) /.test(entry)) throw new Error('symbolic link/submodule');
  const size = Number((await git(repo,'cat-file','-s',`${sha}:${file}`)).trim());
  if (size>200000) throw new Error('file > 200 KB');
  const text = await git(repo,'show',`${sha}:${file}`);
  if (text.includes('\0')) throw new Error('binary');
  return redact(text);
}
export async function collect({repo,base,head,maxContext=260000}, emit=()=>{}) {
  const [baseSha,headSha] = await Promise.all([revision(repo,base),revision(repo,head)]);
  try { await git(repo,'merge-base','--is-ancestor',baseSha,headSha); }
  catch { throw new Error('Base не является предком head. Выберите другую базу.'); }
  const dirty = Boolean((await git(repo,'status','--porcelain','--untracked-files=normal')).trim());
  const commits = (await git(repo,'log','--format=%H%x09%s',`${baseSha}..${headSha}`)).trim().split('\n').filter(Boolean).map(line=>{
    const i=line.indexOf('\t');return {sha:line.slice(0,i),subject:redact(line.slice(i+1))};
  });
  const status=(await git(repo,'diff','--no-ext-diff','--no-textconv','--name-status','-z','--find-renames',baseSha,headSha)).split('\0');
  const changed=[];
  for(let i=0;i<status.length-1;) {
    const change=status[i++], oldPath=status[i++];
    const file=/^[RC]/.test(change)?status[i++]:oldPath;
    changed.push({status:change,path:file,...(/^[RC]/.test(change)?{old_path:oldPath}:{})});
  }
  const evidence={schema_version:1,repository:'DnsHostsGenerator',base_sha:baseSha,head_sha:headSha,
    working_tree_dirty:dirty,commits,changed_files:changed,sources:[],omitted_files:[],truncated_sources:[],coverage_complete:true,checks:[]};
  let budget=maxContext;
  function add(file,kind,text) {
    if (!text) return;
    const limit=Math.min(96000,Math.max(0,budget));
    if(text.length>limit) evidence.truncated_sources.push({path:file,kind,original_chars:text.length,included_chars:limit});
    if(limit===0) return;
    const included=text.slice(0,limit); budget-=included.length;
    evidence.sources.push({id:`S${evidence.sources.length+1}`,path:file,kind,text:included});
  }
  // Workflow/docs are useful context even when unchanged. No arbitrary project config.
  for(const file of ['.github/workflows/build-apps.yml','README.md']) {
    try {add(file,'context',await textBlob(repo,headSha,file));} catch {evidence.omitted_files.push({path:file,reason:'context unavailable'});}
  }
  for(const item of changed) {
    if(!allowed(item.path)||(item.old_path&&!allowed(item.old_path))) {
      evidence.omitted_files.push({path:item.path,reason:'excluded type/path'}); continue;
    }
    try {
      // Validate blobs before asking git to produce a patch: never dereference symlinks.
      await textBlob(repo,headSha,item.path); await textBlob(repo,baseSha,item.old_path||item.path);
      const patch=await git(repo,'diff','--no-ext-diff','--no-textconv','--find-renames','--unified=4',baseSha,headSha,'--',...(item.old_path?[item.old_path]:[]),item.path);
      if (/^Binary files /m.test(patch)) throw new Error('binary');
      add(item.path,'diff',redact(patch));
    } catch {evidence.omitted_files.push({path:item.path,reason:'binary/oversize/symlink/unreadable'});}
  }
  evidence.coverage_complete=evidence.omitted_files.length===0 && evidence.truncated_sources.length===0;
  emit('git',`${commits.length} коммитов · ${changed.length} файлов · ${evidence.sources.length} источников`);
  return evidence;
}

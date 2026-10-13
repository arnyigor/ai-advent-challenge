let state, tab='diff', rendered='';
const $=id=>document.getElementById(id);
const stages={ready:'Готов к запуску',starting:'Запускаем пайплайн…',git:'Git: получаем diff…',context:'RAG: контекст найден',model:'Gemini анализирует изменения…',complete:'✓ Ревью готово',error:'Ошибка пайплайна'};
function node(tag,text,cls){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;}
function render(){
  const key=JSON.stringify([tab,state.context,state.result]);if(key===rendered)return;rendered=key;
  const area=$('content');area.replaceChildren();
  if(tab==='diff'){
    if(!state.context){area.append(node('p','Diff появится после чтения Git-коммитов.','empty'));return;}
    area.append(node('h2',`Изменено файлов: ${state.context.changed_paths.length}`));
    const patch=node('pre','');for(const line of state.context.diff.split('\n'))patch.append(node('div',line,'diff-line '+(line.startsWith('+')?'add':line.startsWith('-')?'remove':'')));area.append(patch);
    for(const f of state.context.files){area.append(node('h3',`${f.path} · новая версия`),node('pre',f.head||'Файл удалён'));}
  }else if(tab==='rag'){
    if(!state.context){area.append(node('p','Источники появятся после поиска.','empty'));return;}
    area.append(node('h2',`Найдено ${state.context.sources.length} источника из базовой версии`));
    area.append(node('p',`SQLite FTS5 / BM25 · ${state.context.index.chunks} чанков · документация + исходники`));
    for(const s of state.context.sources){const box=node('article','','source');box.append(node('h3',`[${s.id}] ${s.path}:${s.line}`),node('p',s.kind==='code'?'Исходный код':'Документация'),node('pre',s.text));area.append(box);}
  }else{
    if(!state.result){area.append(node('p','Ожидаем ответ модели. Ревью появится здесь после завершения запроса.','empty'));return;}
    area.classList.add('review');area.append(node('div',`${state.result.model} · finish_reason=${state.result.finish_reason} · результат сохранён в review.md`,'meta'));
    let code=false,buffer=[];for(const line of state.result.text.split('\n')){
      if(line.trim().startsWith('```')){if(code){area.append(node('pre',buffer.join('\n')));buffer=[];}code=!code;continue;}
      if(code){buffer.push(line);continue;}if(!line.trim())continue;
      area.append(node(line.startsWith('#')?'h3':'p',line.replace(/^#+\s*/,'').replace(/\*\*/g,'').replace(/`/g,'')));
    }
  }
}
async function refresh(){const res=await fetch('/api/state');state=await res.json();window.lastState=state;$('sha').textContent=`base ${state.base.slice(0,9)} → head ${state.head.slice(0,9)}`;$('stage').textContent=stages[state.stage];$('start').disabled=!['ready','complete','error'].includes(state.stage);$('events').replaceChildren(...state.events.map(e=>node('li',`${e.time} · ${e.message}`)));render();}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{tab=b.dataset.tab;document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('selected',x===b));$('content').classList.remove('review');render();}));
$('start').addEventListener('click',async()=>{$('start').disabled=true;const res=await fetch('/api/run',{method:'POST'});if(!res.ok)throw new Error('Pipeline start failed');await refresh();});
refresh();setInterval(()=>refresh().catch(()=>{$('stage').textContent='Нет соединения с сервером';}),500);

const $=s=>document.querySelector(s);
const labels={passed:'Пройдена',failed:'Ошибка',timeout:'Таймаут',not_run:'Не запускалась',unavailable:'Недоступна'};
const statusLabels={blocked:'Заблокировано',incomplete:'Недостаточно подтверждений',checks_passed_review_needed:'Пройдено · требуется просмотр'};
let timer=null,notes='';window.currentRun=null;
function node(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;}
function refs(ids){const group=node('div',undefined,'refs');for(const id of ids){const a=node('a',id);a.href='#source-'+id;a.onclick=()=>{const source=$('#source-'+id);if(source)source.open=true;};group.append(a);}return group;}
async function api(url,options){const response=await fetch(url,options);const data=await response.json();if(!response.ok)throw new Error(data.error||'Ошибка запроса');return data;}
function render(run){
  window.currentRun=run;$('#result').hidden=false;$('#run').disabled=run.state==='running';
  $('#status').textContent=run.state==='running'?'Выполняется…':statusLabels[run.result_status];
  $('#error').hidden=!run.error;$('#error').textContent=run.error||'';
  $('#events').replaceChildren(...run.events.map(e=>{const li=node('li');li.append(node('time',new Date(e.at).toLocaleTimeString('ru-RU')),node('span',e.message));return li;}));
  $('#model-used').textContent=run.model?'Модель: '+run.model:'';
  const e=run.evidence;if(!e){
    for(const id of ['range','counts','coverage'])$('#'+id).textContent='—';
    for(const id of ['changes','risks','manual','uncertainties','sources','check-results','artifacts'])$('#'+id).replaceChildren();
    $('#notes').textContent='Собираем факты…';return;
  }
  $('#range').textContent=e.base_sha.slice(0,7)+' → '+e.head_sha.slice(0,7);$('#counts').textContent=e.commits.length+' / '+e.changed_files.length;
  $('#coverage').textContent=e.coverage_complete?'Полное':'Есть пропуски';
  $('#check-results').replaceChildren(...e.checks.map(c=>{const row=node('div',undefined,'check-row');row.append(node('span',c.id),node('span',labels[c.status],`badge ${c.status}`));return row;}));
  $('#sources').replaceChildren(...e.sources.map(s=>{const d=node('details');d.id='source-'+s.id;d.append(node('summary',s.id+' · '+s.path+' · '+s.kind),node('pre',s.text));return d;}));
  $('#omissions').textContent=[...e.omitted_files.map(f=>'Пропущено: '+f.path+' ('+f.reason+')'),...e.truncated_sources.map(f=>'Обрезано: '+f.path+' '+f.included_chars+'/'+f.original_chars)].join('\n');
  $('#artifacts').replaceChildren(...run.artifacts.map(name=>{const a=node('a',name);a.href=`/api/runs/${run.id}/artifacts/${name}`;a.target='_blank';a.rel='noreferrer';return a;}));
  const a=run.analysis;$('#ai-label').textContent=a?'Живая модель · ссылки проверены':run.state==='running'?'Модель анализирует…':'AI-анализ не получен';
  if(!a){for(const id of ['changes','risks','manual','uncertainties'])$('#'+id).replaceChildren();$('#notes').textContent='Ожидаем завершённый AI-анализ';notes='';return;}
  $('#changes').replaceChildren(...a.changes.map(c=>{const el=node('div',undefined,'change');el.append(node('h3',c.title),node('p',c.user_impact),refs(c.evidence_ids));return el;}));
  $('#risks').replaceChildren(node('h3','Что проверить перед выпуском'),...a.risks.map(r=>{const el=node('div',undefined,'risk');el.append(node('span',r.severity.toUpperCase()),node('div',r.scenario),refs(r.evidence_ids));return el;}));
  $('#manual').replaceChildren(node('h3','Ручные проверки · предложены AI'),...a.manual_checks.map(c=>{const el=node('div',undefined,'manual');el.append(node('strong',c.action),node('div','Ожидается: '+c.expected_result),refs(c.evidence_ids));return el;}));
  $('#uncertainties').replaceChildren(node('h3','Что остаётся неизвестным'),...a.uncertainties.map(x=>node('p',x,'muted')));
  notes=a.release_notes;$('#notes').textContent=notes;
}
async function poll(id){try{const run=await api('/api/runs/'+id);render(run);if(run.state==='running')timer=setTimeout(()=>poll(id),1000);}catch(e){$('#error').hidden=false;$('#error').textContent=e.message;$('#run').disabled=false;}}
$('#provider').onchange=()=>{$('#privacy').textContent=$('#provider').value==='local'?'Исходники будут переданы настроенному локальному endpoint. Облачного переключения нет.':'При запуске разрешённые фрагменты исходников и diff будут переданы выбранному облачному провайдеру. Секреты исключаются по правилам корпуса.';};
$('#form').onsubmit=async event=>{event.preventDefault();clearTimeout(timer);$('#run').disabled=true;$('#error').hidden=true;$('#result').hidden=true;
  try{const run=await api('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base:$('#base').value,head:$('#head').value,provider:$('#provider').value,model:$('#model').value,runChecks:$('#checks').checked})});await poll(run.id);}
  catch(e){$('#error').hidden=false;$('#error').textContent=e.message;$('#run').disabled=false;}
};
$('#copy').onclick=async()=>{try{await navigator.clipboard.writeText(notes);$('#copy').textContent='Скопировано';setTimeout(()=>$('#copy').textContent='Копировать',1500);}catch{$('#error').hidden=false;$('#error').textContent='Скопируйте текст из блока описания';}};
api('/api/config').then(config=>{for(const id of ['base','head','provider','model'])$('#'+id).value=config[id];$('#provider').onchange();
  $('#tags').replaceChildren(...config.tags.map(tag=>{const o=node('option');o.value=tag;return o;}));
  $('#availability').textContent=config.repoAvailable?'Репозиторий подключён · '+config.tags.length+' тегов':'Укажите DAY35_REPO или клонируйте репозиторий по README';
  if(config.latest)void poll(config.latest);
}).catch(e=>{$('#availability').textContent=e.message;});

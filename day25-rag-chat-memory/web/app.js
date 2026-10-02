const $=s=>document.querySelector(s);
function node(tag,text,cls){const n=document.createElement(tag);if(text!==null&&text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
let sessionId=null,busy=false;

function renderState(state){
 $('#state-goal').textContent=state.goal||'—';
 const lists=[['clarified','#state-clarified','count-clarified'],['constraints','#state-constraints','count-constraints'],['terms','#state-terms','count-terms']];
 for(const [key,selector,counter] of lists){
  const box=$(selector);box.replaceChildren();
  const items=state[key]||[];
  $(`#${counter}`).textContent=items.length;
  if(!items.length)box.append(node('li','пока ничего','muted'));
  items.forEach(item=>box.append(node('li',item)));
 }
 $('#state-version').textContent=`Версия состояния: ${state.version} · сессия ${state.session_id||sessionId||''}`;
 $('#state-errors').textContent='';
}

function renderSources(container,sources,quotes){
 if(!sources||!sources.length){container.append(node('p','Источников нет: подтверждений не нашлось','empty'));return;}
 sources.forEach((s,i)=>{
  const card=node('article','','source-card');
  card.append(node('b',`Источник ${i+1}`),node('strong',s.source),node('small',`Раздел: ${s.section}`),node('small',`Фрагмент: ${s.chunk_id}`));
  const linked=quotes.filter(q=>q.chunk_id===s.chunk_id);
  if(linked.length){
   const details=node('details');details.append(node('summary',`Цитаты (${linked.length})`));
   linked.forEach(q=>details.append(node('blockquote',q.quote)));
   card.append(details);
  }
  container.append(card);
 });
}

function renderTurn(item){
 const wrap=node('article','',`turn ${item.role}`);
 if(item.role==='user'){wrap.append(node('p',item.content,'user-text'));return wrap;}
 const p=item.payload||{};
 const ok=p.status==='answered';
 const head=node('div','',`turn-head ${ok?'good':'warn'}`);
 head.append(node('span',ok?'Подтверждён источниками':'Не знаю'),node('small',`ход ${p.turn??'·'} · поиск: ${p.search_query||'—'} · ${p.elapsed_sec??''} с`));
 wrap.append(head);
 if(p.memory_used?.goal)wrap.append(node('p',`Учтённая цель: ${p.memory_used.goal}`,'memory-used'));
 if(p.memory_used?.constraints?.length)wrap.append(node('p',`Учтённые ограничения: ${p.memory_used.constraints.join('; ')}`,'memory-used'));
 if(ok){p.claims.forEach(c=>wrap.append(node('p',c.text,'answer-line')));}
 else{wrap.append(node('p',item.content||p.answer||'','unknown-answer'));}
 const src=node('div','','sources');wrap.append(node('b','Источники','sources-title'),src);
 renderSources(src,p.sources,p.quotes);
 if(p.condense_fallback)wrap.append(node('p','Запрос не переформулирован: использован текст сообщения','fallback'));
 if(p.state_errors&&p.state_errors.length)wrap.append(node('p',`Состояние не обновлено (${p.state_errors.length} ошибок валидации); сохранена предыдущая версия`,'state-errors'));
 wrap.append(node('p',`Память задачи → версия ${p.task_state?p.task_state.version:'—'}`,'state-version-line'));
 return wrap;
}

function appendTurn(item){const box=$('#messages'),turn=renderTurn(item);box.append(turn);box.scrollTop=item.role==='assistant'?turn.offsetTop:box.scrollHeight;}

async function newSession(){
 if(busy)return;
 const r=await fetch('/api/session',{method:'POST'});const v=await r.json();
 if(!r.ok){$('#status').textContent='Ошибка: '+v.error;return;}
 sessionId=v.session_id;$('#messages').replaceChildren();renderState(v.task_state);
 const sessionUrl=new URL(location.href);sessionUrl.searchParams.set('session',sessionId);history.replaceState(null,'',sessionUrl);
 $('#session-id').textContent=`сессия: ${sessionId}`;
 await loadSessionList();$('#status').textContent='Новая сессия создана';
}

async function loadSession(sessionIdValue){
 if(busy)return;
 const r=await fetch(`/api/session?id=${encodeURIComponent(sessionIdValue)}`);const v=await r.json();
 if(!r.ok){$('#status').textContent='Ошибка: '+v.error;return;}
 sessionId=v.session_id;$('#messages').replaceChildren();
 const sessionUrl=new URL(location.href);sessionUrl.searchParams.set('session',sessionId);history.replaceState(null,'',sessionUrl);
 v.history.forEach(item=>appendTurn(item));
 const last=v.history.filter(h=>h.role==='assistant').pop();
 renderState(v.task_state);
 $('#session-id').textContent=`сессия: ${sessionId}`;
 $('#status').textContent=`Сессия возобновлена: ${v.history.length} сообщений`;
}

async function loadSessionList(){
 const r=await fetch('/api/state');const v=await r.json();if(!r.ok)return;
 const select=$('#session-select');select.replaceChildren(node('option','Возобновить сессию…',''));
 select.value='';
 v.sessions.forEach(s=>{const o=node('option',`${s.session_id} · ${s.messages} сообщ.`);o.value=s.session_id;select.append(o);if(s.session_id===sessionId)select.value=s.session_id;});
}

async function send(){
 if(busy||!sessionId)return;
 const text=$('#message').value.trim();
 if(!text){$('#status').textContent='Введите сообщение';return;}
 busy=true;$('#send').disabled=true;$('#new-session').disabled=true;$('#session-select').disabled=true;$('#status').textContent='Ищу документы, проверяю цитаты и сохраняю память задачи…';
 appendTurn({role:'user',content:text});$('#message').value='';
 try{
  const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,message:text})});
  const v=await r.json();
  if(!r.ok)throw Error(v.error);
  appendTurn({role:'assistant',content:v.answer,payload:v});
  renderState(v.task_state);
  $('#status').textContent=v.status==='answered'?'Готово: ответ с источниками':'Готово: не знаю, требуется уточнение';
 }catch(e){$('#status').textContent='Ошибка: '+e.message;$('#messages').lastChild?.remove();$('#message').value=text;}
 finally{busy=false;$('#send').disabled=false;$('#new-session').disabled=false;$('#session-select').disabled=false;loadSessionList().catch(()=>{});}
}

const demoSteps=[
 ['Что проверяем','Чат ищет информацию заново на каждом ходу. Слева — ответ и доказательства, справа — память задачи.'],
 ['1. Первый вопрос','Спрашиваем о защите RSS от повторных статей. Цель и термины появляются в памяти после ответа.'],
 ['2. Источник можно проверить','Откройте «Цитаты»: показан дословный фрагмент кода с именем файла. Ответ прошёл проверку доказательств.'],
 ['3. Уточнение без повторения темы','«В каком файле это реализовано?» — чат понимает «это» из истории и памяти; снова выполняет поиск.'],
 ['4. Фиксируем ограничение','Указываем: только стандартная библиотека. Ограничение записывается отдельно от истории.'],
 ['5. Память влияет на следующий ответ','Просим итог без повторения ограничения. Под ответом видно, какая цель и какие ограничения переданы модели.'],
 ['6. Восстанавливаем сессию','Создаём новую сессию, затем выбираем предыдущую. История, источники и память загружаются из SQLite.'],
 ['7. Два длинных диалога','Показываем отчёт реальных прогонов: по 12 сообщений, проверка цитат, цели, ограничений и терминов.']
];
let demoIndex=Math.max(0,Math.min(demoSteps.length-1,Number(new URLSearchParams(location.search).get('step'))||0));
function showDemo(){const [title,detail]=demoSteps[demoIndex];$('#demo-step').textContent=`ДЕМО · ${demoIndex+1} / ${demoSteps.length}`;$('#demo-title').textContent=title;$('#demo-detail').textContent=detail;$('#demo-next').disabled=demoIndex===demoSteps.length-1;}
if(new URLSearchParams(location.search).has('demo')){document.body.classList.add('demo');$('#demo-guide').hidden=false;showDemo();}
$('#demo-next').onclick=()=>{if(demoIndex<demoSteps.length-1){demoIndex++;showDemo();const u=new URL(location.href);u.searchParams.set('step',demoIndex);history.replaceState(null,'',u);}};
$('#show-evaluation').onclick=async()=>{try{const r=await fetch('/api/evaluation'),v=await r.json();if(!r.ok)throw Error(v.error);const box=$('#evaluation-results');box.replaceChildren(node('p',`Реальный прогон · ${v.model} · ${new Date(v.created_at).toLocaleString('ru-RU')}`));for(const s of v.scenarios){const x=s.summary;box.append(node('h3',s.title),node('p',`${v.summary[s.id]==='passed'?'ПРОЙДЕН':'НЕ ПРОЙДЕН'} · ${x.turns} сообщений · цель: ${x.goal_retained?'сохранена':'потеряна'} · ограничения: ${x.constraints_retained?'сохранены':'потеряны'} · термины: ${x.terms_retained?'сохранены':'потеряны'}`));box.append(node('p',`Ответы с источниками: ${x.answers_with_sources??"—"}/${x.answered_turns??"—"}. Честных отказов без выдуманных цитат: ${x.refused_turns??"—"}. Проверки цитат: ${x.per_turn_checks.exact_quotes}/${x.turns}.`));}}catch(e){$('#evaluation-results').textContent=e.message;}};

$('#send').onclick=send;
$('#new-session').onclick=newSession;
$('#session-select').onchange=e=>{if(e.target.value)loadSession(e.target.value);};
$('#message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
const resumeId=new URLSearchParams(location.search).get('session');
(resumeId?loadSession(resumeId).then(loadSessionList):newSession()).catch(e=>{$('#status').textContent='Ошибка: '+e.message;});

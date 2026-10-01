const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
function node(tag,text,cls){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;}
const reasons={verified:'Все утверждения подтверждены',weak_context:'Релевантность ниже порога',insufficient_evidence:'В найденных чанках нет ответа',invalid_evidence:'Доказательства не прошли проверку'};
let state,current,tourTimer;
function stopTour(){clearTimeout(tourTimer);tourTimer=null;$('#tour').textContent='Показать по шагам';}
function highlightClaim(claim){
 $$('.claim-row').forEach(n=>n.classList.toggle('linked',Number(n.dataset.claim)===claim));
 const chunks=new Set(current.quotes.filter(q=>q.claim===claim).map(q=>q.chunk_id));
 $$('.source-card').forEach(n=>n.classList.toggle('linked',chunks.has(n.dataset.chunk)));
 $$('.quote-card').forEach(n=>n.classList.toggle('linked',Number(n.dataset.claim)===claim));
}
function focusStep(step,claim=1,scroll=true){
 if(!current)return;
 $$('.proof-panel,#checks-panel,#benchmark,#probes').forEach(n=>n.classList.remove('spotlight'));
 $$('.steps button').forEach(n=>{n.classList.toggle('active',n.dataset.step===step);n.setAttribute('aria-pressed',String(n.dataset.step===step));});
 const sourceNo=current.sources.findIndex(s=>s.chunk_id===current.quotes.find(q=>q.claim===claim)?.chunk_id)+1;
 const count=current.claims.length;
 let id,title,detail;
 if(current.status==='unknown'&&['answer','sources','quotes'].includes(step)){
  id='answer-panel';title='Не знаю — вместо неподтверждённого ответа';detail=`${reasons[current.reason]}. Прочитайте просьбу уточнить. Источники и цитаты пустые, потому что подтверждений нет.`;
 }else if(step==='answer'){
  id='answer-panel';title=`① Сначала прочитайте утверждение У${claim}`;detail=`В ответе ${count} утверждений. Жёлтая подсветка связывает У${claim} с источником И${sourceNo} и цитатами справа.`;
 }else if(step==='sources'){
  id='sources-panel';title=`② Проверьте источник И${sourceNo}`;detail='source показывает файл, section — раздел, chunk_id — точный найденный фрагмент. Метаданные сверены с индексом.';
 }else if(step==='quotes'){
  id='quotes-panel';title=`③ Сравните выделенную цитату с У${claim}`;detail='Цитата дословно взята из чанка. Она должна подтверждать всё утверждение, включая условия и ограничения.';
 }else if(step==='checks'){
  id='checks-panel';title='④ Посмотрите результаты проверки';detail='Три требования задания проверены отдельно. Дополнительно код проверил дословность цитат.';
 }else if(step==='benchmark'){
  id='benchmark';title='Проверка каждого из 10 вопросов';detail='В каждой строке: источники, цитаты и смысл. Откройте любой ответ, чтобы проверить его доказательства.';
 }else{
  id='probes';title='Правило порога: слабый контекст → «не знаю»';detail='Откройте отказ. Ниже видны максимальная релевантность, порог и просьба уточнить.';
 }
 highlightClaim(claim);$('#'+id).classList.add('spotlight');$('#guide-step').textContent='СМОТРИТЕ НА ВЫДЕЛЕННЫЙ БЛОК';$('#guide-title').textContent=title;$('#guide-detail').textContent=detail;
 if(scroll){const target=['benchmark','probes','checks-panel'].includes(id)?$('#'+id):$('#walkthrough');target.scrollIntoView({block:'start',behavior:'instant'});}
}
function show(result){
 stopTour();current=result;$('#question').value=result.question;$('#current-question').textContent=result.question;
 const ok=result.status==='answered';$('#decision').textContent=ok?'Подтверждён':'Не знаю';$('#decision').className=`pill ${ok?'good':'warn'}`;
 $('#answer').replaceChildren();if(ok){result.claims.forEach((c,i)=>{const row=node('button','', 'claim-row');row.dataset.claim=i+1;row.append(node('b',`У${i+1}`),node('span',c.text));row.onclick=()=>{stopTour();focusStep('quotes',i+1);};$('#answer').append(row);});}else{$('#answer').append(node('p',result.answer,'unknown-answer'));}
 $('#reason').textContent=`${reasons[result.reason]||result.reason} · ${result.elapsed_sec} с`;
 const maxScore=Math.max(-1,...result.candidates.map(c=>c.score));
 $('#threshold-status').textContent=result.reason==='weak_context'?`Макс. релевантность ${maxScore.toFixed(3)} < порог ${result.similarity_threshold.toFixed(3)} → генерация ответа пропущена`:'';
 $('#sources').replaceChildren();result.sources.forEach((s,i)=>{const card=node('button','','source-card');card.dataset.chunk=s.chunk_id;card.append(node('b',`И${i+1} · source`),node('strong',s.source),node('small',`section: ${s.section}`),node('small',`chunk_id: ${s.chunk_id}`));card.onclick=()=>{const q=result.quotes.find(q=>q.chunk_id===s.chunk_id);stopTour();focusStep('quotes',q.claim);};$('#sources').append(card);});
 $('#quotes').replaceChildren();result.quotes.forEach((q,i)=>{const s=result.sources.findIndex(s=>s.chunk_id===q.chunk_id)+1;const card=node('article','','quote-card');card.dataset.claim=q.claim;card.append(node('b',`Ц${i+1} → У${q.claim} · источник И${s}`),node('blockquote',q.quote));$('#quotes').append(card);});
 if(!ok){$('#sources').append(node('p','Нет подтверждающих источников','empty'));$('#quotes').append(node('p','Нет подтверждающих цитат','empty'));}
 $('#source-count').textContent=result.sources.length;$('#quote-count').textContent=result.quotes.length;
 $('#checks').replaceChildren();for(const [label,passed] of [['Источники',!!result.sources.length],['Цитаты',!!result.quotes.length],['Смысл подтверждён',ok&&result.semantic_check?.supported===true],['Цитаты дословные',ok]])$('#checks').append(node('span',`${passed?'✓':'—'} ${label}`,`check ${passed?'passed':'missing'}`));
 $('#meaning-reason').textContent=ok?result.semantic_check.reason:'Ответ по существу не дан. Ассистент просит уточнение и не выдумывает доказательства.';
 $('#model-output').textContent=result.model_output?JSON.stringify(result.model_output,null,2):'Генерация ответа пропущена: слабый контекст.';
 $('#rewrite').textContent=`Поисковый запрос: ${result.search_query}`;
 $('#retrieval-settings').textContent=`Порог cosine: ${result.similarity_threshold} · Максимальный score: ${Math.max(-1,...result.candidates.map(c=>c.score)).toFixed(3)} · Найдено кандидатов: ${result.candidates.length}`;
 $('#candidates').replaceChildren();for(const c of result.candidates){const card=node('article','',`candidate ${c.accepted?'accepted':'rejected'}`);card.append(node('strong',c.source),node('p',c.text),node('footer',`cosine ${c.score.toFixed(3)} · ${(c.channels||[]).join(' + ')} · ${c.reason}`));$('#candidates').append(card);}
 $('#tour').disabled=false;focusStep('answer');
}
$$('.steps button').forEach(b=>b.onclick=()=>{stopTour();focusStep(b.dataset.step);});
$('#tour').onclick=()=>{if(tourTimer){stopTour();return;}$('#tour').textContent='Остановить показ';const steps=['answer','sources','quotes','checks'];let i=0;function next(){focusStep(steps[i++]);if(i<steps.length)tourTimer=setTimeout(next,6500);else tourTimer=setTimeout(stopTour,6500);}next();};
$('#preset').onchange=()=>{$('#question').value=state.questions[Number($('#preset').value)].question;};
$('#run').onclick=async()=>{stopTour();$('#run').disabled=true;$('#status').textContent='Ищем контекст → получаем ответ, источники и цитаты → проверяем…';try{const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:$('#question').value})});const v=await r.json();if(!r.ok)throw Error(v.error);show(v);$('#status').textContent=v.status==='answered'?'Готово: ответ с проверенными доказательствами':'Готово: не знаю, требуется уточнение';}catch(e){$('#status').textContent='Ошибка: '+e.message;}finally{$('#run').disabled=false;}};
fetch('/api/state').then(r=>r.json()).then(v=>{state=v;v.questions.forEach((q,i)=>{const o=node('option',`${i+1}. ${q.question}`);o.value=i;$('#preset').append(o);});$('#question').value=v.questions[0].question;
 if(!v.report){$('#score').textContent='Запустите evaluate.py';return;}const s=v.report.summary;$('#score').textContent=`${s.meaning_supported}/${s.questions} ответов подтверждены`;
 for(const [name,key] of [['Источники','has_sources'],['Цитаты','has_quotes'],['Смысл','meaning_supported'],['Дословность','exact_quotes']]){const c=node('article','','metric');c.append(node('small',name),node('strong',`${s[key]}/${s.questions}`));$('#summary').append(c);}
 v.report.items.forEach((row,i)=>{const tr=node('tr','');tr.append(node('td',`${i+1}. ${row.question}`));for(const key of ['has_sources','has_quotes','meaning_supported'])tr.append(node('td',row.checks[key]?'✓ Есть':'✗ Нет',row.checks[key]?'yes':'no'));const td=node('td','');const b=node('button','Открыть');b.onclick=()=>{show(row.result);};td.append(b);tr.append(td);$('#questions').append(tr);});
 for(const p of v.report.probes){const c=node('article','','probe-card');const max=Math.max(-1,...p.result.candidates.map(c=>c.score));c.append(node('h3',p.question),node('p',`Макс. cosine ${max.toFixed(3)} · порог ${p.result.similarity_threshold}`,p.result.reason==='weak_context'?'threshold-proof':''),node('p',p.passed?'✓ Не знаю + уточнение': '✗ Проверка не пройдена'));const b=node('button','Показать отказ');b.onclick=()=>{show(p.result);};c.append(b);$('#probe-results').append(c);}
}).catch(e=>{$('#status').textContent=e.message;});

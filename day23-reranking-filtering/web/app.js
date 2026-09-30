const $=selector=>document.querySelector(selector);
let state;
function node(tag,text,className){const value=document.createElement(tag);value.textContent=text;if(className)value.className=className;return value;}
function percent(value){return `${Math.round((value||0)*100)}%`;}
function renderQuestions(){
  const reportById=new Map((state.report?.items||[]).map(item=>[item.id,item]));
  $('#questions').replaceChildren();$('#preset').replaceChildren();
  state.questions.forEach((item,index)=>{
    const option=node('option',`${index+1}. ${item.question}`);option.value=String(index);$('#preset').append(option);
    const card=node('article','', 'question');card.append(node('h3',`${index+1}. ${item.question}`),node('p',`Ожидание: ${item.expectation}`));
    const result=reportById.get(item.id);if(result){const badges=node('div','', 'badges');badges.append(node('span',`baseline ${percent(result.baseline.answer_score)}`,'badge'),node('span',`improved ${percent(result.improved.answer_score)}`,'badge good'),node('span',`оставлено ${result.improved.kept_count}/${result.improved.candidates.length}`,'badge filter'));card.append(badges);}
    $('#questions').append(card);
  });
  const summary=state.report?.summary;
  $('#score').textContent=summary?`${percent(summary.baseline_answer_score)} → ${percent(summary.improved_answer_score)}`:'запустите evaluate.py';
  $('#summary').replaceChildren();
  if(summary){[['Полнота ответа',`${percent(summary.baseline_answer_score)} → ${percent(summary.improved_answer_score)}`],['Recall источников',`${percent(summary.baseline_source_recall)} → ${percent(summary.improved_source_recall)}`],['Среднее после фильтра',summary.improved_avg_kept.toFixed(1)],['Отсеяно кандидатов',summary.improved_avg_rejected.toFixed(1)]].forEach(([label,value])=>{const card=node('article','', 'metric');card.append(node('small',label),node('strong',value));$('#summary').append(card);});}
  $('#question').value=state.questions[0].question;
}
function renderCandidates(items){
  $('#candidates').replaceChildren();
  for(const item of items){const card=node('article','',`candidate ${item.accepted?'accepted':'rejected'}`);const head=node('div','', 'candidate-head');const left=node('div','');left.append(node('span',`vector #${item.original_rank} → rerank ${item.reranked_rank?`#${item.reranked_rank}`:'—'}${item.final_rank?` → prompt #${item.final_rank}`:''}`,'rank'),node('strong',item.source),node('small',item.section));head.append(left,node('span',item.accepted?'ПРИНЯТ':'ОТСЕЧЁН',`decision ${item.accepted?'yes':'no'}`));card.append(head,node('p',item.text),node('footer',`cosine ${item.score.toFixed(3)} · lexical ${item.lexical_overlap.toFixed(3)} · rerank ${item.rerank_score.toFixed(3)} · ${item.reason}`));$('#candidates').append(card);}
}
$('#preset').addEventListener('change',()=>{$('#question').value=state.questions[Number($('#preset').value)].question;});
$('#run').addEventListener('click',async()=>{
  $('#run').disabled=true;$('#status').textContent='Baseline, query rewrite и improved RAG выполняются последовательно…';$('#baseline-answer').textContent='Получаем baseline…';$('#improved-answer').textContent='Переписываем запрос и фильтруем…';$('#rewritten-query').textContent='Генерируется…';$('#candidates').replaceChildren(node('p','Ищем top-8 кандидатов…','muted'));
  try{const response=await fetch('/api/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:$('#question').value})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Ошибка запроса');
    const base=data.baseline,improved=data.improved;$('#baseline-answer').textContent=base.answer;$('#improved-answer').textContent=improved.answer;$('#rewritten-query').textContent=improved.search_query+(improved.rewrite_fallback?' · fallback к исходному вопросу':'');
    $('#baseline-meta').textContent=`${base.elapsed_sec} с · ${base.sources.length} чанка · prompt ${base.prompt_chars}`;$('#improved-meta').textContent=`${improved.elapsed_sec} с · ${improved.sources.length} чанка · prompt ${improved.prompt_chars}`;
    const rejected=improved.candidates.filter(item=>!item.accepted).length;$('#filter-stats').textContent=`до ${improved.candidates.length} · принято ${improved.sources.length} · отсечено ${rejected}`;renderCandidates(improved.candidates);$('#status').textContent=`Готово: top-${improved.top_k_before} → threshold ${improved.similarity_threshold.toFixed(2)} → top-${improved.sources.length}`;
  }catch(error){$('#status').textContent=`Ошибка: ${error.message}`;$('#baseline-answer').textContent='—';$('#improved-answer').textContent='—';}finally{$('#run').disabled=false;}
});
fetch('/api/state').then(response=>response.json()).then(data=>{state=data;const s=data.settings;$('#pipe-before').textContent=`top-${s.top_k_before}`;$('#pipe-threshold').textContent=`score ≥ ${s.similarity_threshold.toFixed(2)}`;$('#pipe-after').textContent=`top-${s.top_k_after}`;renderQuestions();}).catch(error=>{$('#status').textContent=`Ошибка загрузки: ${error.message}`;});

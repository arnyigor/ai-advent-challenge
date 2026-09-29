const $=selector=>document.querySelector(selector);
let state;
function node(tag,text,className){const value=document.createElement(tag);value.textContent=text;if(className)value.className=className;return value;}
function renderQuestions(){
  const reportById=new Map((state.report?.items||[]).map(item=>[item.id,item]));
  $('#questions').replaceChildren();$('#preset').replaceChildren();
  state.questions.forEach((item,index)=>{
    const option=node('option',`${index+1}. ${item.question}`);option.value=String(index);$('#preset').append(option);
    const card=node('article','', 'question');card.append(node('h3',`${index+1}. ${item.question}`),node('p',`Ожидание: ${item.expectation}`));
    const sources=node('p','Источники: ');item.expected_sources.forEach((source,i)=>{if(i)sources.append(' · ');sources.append(node('code',source));});card.append(sources);
    const result=reportById.get(item.id);if(result){const badges=node('div','', 'badges');badges.append(node('span',`без RAG ${Math.round(result.plain.answer_score*100)}%`,'badge'),node('span',`RAG ${Math.round(result.rag.answer_score*100)}%`,'badge good'),node('span',`источники ${Math.round(result.rag.source_recall*100)}%`,'badge good'));card.append(badges);}
    $('#questions').append(card);
  });
  const summary=state.report?.summary;$('#score').textContent=summary?`RAG ${Math.round(summary.rag_answer_score*100)}% · без RAG ${Math.round(summary.plain_answer_score*100)}%`:'запустите evaluate.py';
  $('#question').value=state.questions[0].question;
}
function renderChunks(items){
  $('#chunks').replaceChildren();
  for(const item of items){const card=node('article','', 'chunk');const head=node('div','', 'chunk-head');const left=node('div','');left.append(node('span',`#${item.rank} · score ${item.score.toFixed(3)}`,'rank'),node('strong',item.source),node('small',item.section));head.append(left,node('small',item.chunk_id));card.append(head,node('p',item.text));$('#chunks').append(card);}
}
$('#preset').addEventListener('change',()=>{$('#question').value=state.questions[Number($('#preset').value)].question;});
$('#run').addEventListener('click',async()=>{
  $('#run').disabled=true;$('#status').textContent='Два последовательных запроса к одной модели…';$('#plain-answer').textContent='Ожидаем ответ без контекста…';$('#rag-answer').textContent='Поиск и ответ с контекстом…';$('#chunks').replaceChildren(node('p','Вычисляем embedding вопроса и ищем top-4…','muted'));
  try{const response=await fetch('/api/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:$('#question').value})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Ошибка запроса');
    $('#plain-answer').textContent=data.plain.answer;$('#rag-answer').textContent=data.rag.answer;$('#plain-meta').textContent=`${data.plain.model} · ${data.plain.elapsed_sec} с · prompt ${data.plain.prompt_chars} зн.`;$('#rag-meta').textContent=`${data.rag.model} · ${data.rag.elapsed_sec} с · prompt ${data.rag.prompt_chars} зн.`;$('#embedding').textContent=`${data.rag.embedding_model} · top-${data.rag.sources.length}`;renderChunks(data.rag.sources);$('#status').textContent=`Готово: без RAG ${data.plain.elapsed_sec} с · с RAG ${data.rag.elapsed_sec} с · источников ${new Set(data.rag.sources.map(item=>item.source)).size}`;
  }catch(error){$('#status').textContent=`Ошибка: ${error.message}`;$('#plain-answer').textContent='—';$('#rag-answer').textContent='—';}finally{$('#run').disabled=false;}
});
fetch('/api/state').then(response=>response.json()).then(data=>{state=data;renderQuestions();}).catch(error=>{$('#status').textContent=`Ошибка загрузки: ${error.message}`;});

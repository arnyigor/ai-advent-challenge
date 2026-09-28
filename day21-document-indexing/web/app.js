const $=selector=>document.querySelector(selector);
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const size=value=>value<1024?`${value} B`:`${(value/1024).toFixed(1)} KB`;
let state;
const DEMO_SOURCE='day21-document-indexing/corpus/atlas-handbook.md';
const wait=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));

function statCards(item){
  if(!item)return '<div class="number"><b>—</b><span>нет индекса</span></div>';
  return [['chunks','чанков'],['avg_chars','средний размер'],['embeddings','эмбеддингов'],['db_size_bytes','размер SQLite']]
    .map(([key,label])=>`<div class="number"><b>${key==='db_size_bytes'?size(item[key]):item[key]}</b><span>${label}</span></div>`).join('');
}
function renderMetrics(report){
  if(!report){$('#metrics').className='metrics empty';$('#metrics').textContent='Сначала постройте индексы';return;}
  $('#query-count').textContent=report.queries;
  const f=report.strategies.fixed,s=report.strategies.structure;
  const rows=[['Hit@1',f.hit_at_1,s.hit_at_1],['Hit@5',f.hit_at_5,s.hit_at_5],['MRR@5',f.mrr_at_5,s.mrr_at_5],['Median chars',f.median_chars,s.median_chars],['P95 chars',f.p95_chars,s.p95_chars],['SQLite size',size(f.db_size_bytes),size(s.db_size_bytes)]];
  $('#metrics').className='metrics';$('#metrics').innerHTML='<div class="head">Метрика</div><div class="head fixed-cell">Fixed</div><div class="head structure-cell">Structure</div>'+rows.map(row=>row.map((cell,index)=>`<div class="${index===1?'fixed-cell':index===2?'structure-cell':''}">${cell}</div>`).join('')).join('');
}
async function loadState(){
  state=await fetch('/api/state').then(response=>response.json());
  $('#corpus-files').textContent=state.corpus.files;$('#corpus-pages').textContent=state.corpus.pages_at_500_words;
  $('#fixed-stats').innerHTML=statCards(state.indexes.fixed);$('#structure-stats').innerHTML=statCards(state.indexes.structure);
  $('#embedding-dim').textContent=state.indexes.fixed?.embedding_dim??'—';renderMetrics(state.comparison);
  $('#status').textContent=state.indexes.fixed&&state.indexes.structure?`Готово · ${state.indexes.fixed.embedding_model}`:'Индексы не построены';
  if(state.indexes.structure)await loadSources();
}
async function loadSources(){
  const data=await fetch('/api/sources').then(response=>response.json());
  $('#source').innerHTML=data.sources.map(item=>`<option value="${escapeHtml(item.source)}">${escapeHtml(item.source)} · ${item.chunks} chunks</option>`).join('');
  const preferred=data.sources.find(item=>item.source===DEMO_SOURCE)||data.sources.find(item=>item.source.includes('orchestrator.py'))||data.sources[0];
  if(preferred){$('#source').value=preferred.source;await loadChunks(preferred.source)}
}
function chunkCard(item){return `<article class="chunk"><div class="meta">${escapeHtml(item.chunk_id)} · ${item.char_count} chars<br>section: ${escapeHtml(item.section)}</div><div class="snippet">${escapeHtml(item.text)}</div></article>`}
async function loadChunks(source){
  const data=await fetch(`/api/chunks?source=${encodeURIComponent(source)}`).then(response=>response.json());
  for(const name of ['fixed','structure'])$(`#${name}-chunks`).innerHTML=(data[name]||[]).map(chunkCard).join('')||'<p>Нет чанков</p>';
}
async function runDemo(){
  const button=$('#demo-run');button.disabled=true;
  const [documentResponse,chunksResponse]=await Promise.all([
    fetch(`/api/document?source=${encodeURIComponent(DEMO_SOURCE)}`),
    fetch(`/api/chunks?source=${encodeURIComponent(DEMO_SOURCE)}`),
  ]);
  const documentData=await documentResponse.json(),chunks=await chunksResponse.json();
  if(!documentResponse.ok||!chunksResponse.ok)throw new Error(documentData.error||chunks.error||'Демо-документ не найден в индексе');
  $('.document-stage').classList.add('visible');
  $('#demo-source').textContent=documentData.text;
  $('#demo-document-size').textContent=`${documentData.chars} символов · ${documentData.language}`;
  $('#demo-fixed-count').textContent=chunks.fixed.length;$('#demo-structure-count').textContent=chunks.structure.length;
  const messages=[
    `Прочитан ${documentData.source}`,
    `Создано ${chunks.fixed.length} fixed и ${chunks.structure.length} structural chunks`,
    `Сгенерированы нормализованные векторы размерности ${state.indexes.fixed.embedding_dim}`,
    `Чанки и metadata сохранены в fixed.sqlite3 и structure.sqlite3`,
  ];
  $('#demo-log').innerHTML=messages.map(message=>`<li>${escapeHtml(message)}</li>`).join('');
  const steps=[...document.querySelectorAll('.flow-step')],logs=[...document.querySelectorAll('#demo-log li')];
  for(const item of [...steps,...logs])item.classList.remove('active','done','current','complete');
  for(let index=0;index<steps.length;index++){
    steps[index].classList.add('active');logs[index].classList.add('current');
    $('#status').textContent=messages[index];await wait(1200);
    steps[index].classList.remove('active');steps[index].classList.add('done');
    logs[index].classList.remove('current');logs[index].classList.add('complete');
  }
  $('#status').textContent='Документ проиндексирован · 2 стратегии · 384 dimensions';button.disabled=false;
}
function resultCard(item,index){return `<article class="result"><span class="score">${item.score.toFixed(3)}</span><strong>${index+1}. ${escapeHtml(item.file)}</strong><div class="meta">${escapeHtml(item.section)} · ${escapeHtml(item.chunk_id)}</div><div class="snippet">${escapeHtml(item.text)}</div></article>`}
$('#source').addEventListener('change',event=>loadChunks(event.target.value));
$('#demo-run').addEventListener('click',()=>runDemo().catch(error=>{$('#status').textContent=`Ошибка: ${error.message}`;$('#demo-run').disabled=false}));
$('#search-form').addEventListener('submit',async event=>{event.preventDefault();$('#status').textContent='Векторный поиск…';try{const response=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:$('#query').value})});const data=await response.json();if(!response.ok)throw new Error(data.error);for(const name of ['fixed','structure'])$(`#${name}-results`).innerHTML=data.results[name].map(resultCard).join('');$('#status').textContent=`Поиск завершён · ${data.model}`}catch(error){$('#status').textContent=`Ошибка: ${error.message}`}});
$('#build').addEventListener('click',async()=>{const button=$('#build');button.disabled=true;$('#status').textContent='Chunking и эмбеддинги…';try{const response=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});const data=await response.json();if(!response.ok)throw new Error(data.error);await loadState()}catch(error){$('#status').textContent=`Ошибка: ${error.message}`}finally{button.disabled=false}});
loadState().catch(error=>{$('#status').textContent=`Ошибка: ${error.message}`});

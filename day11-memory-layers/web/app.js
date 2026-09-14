const $ = id => document.getElementById(id);
const fields = {user:$('user'),session:$('session'),task:$('task')};
function ids(){return {user_id:fields.user.value.trim(),session_id:fields.session.value.trim(),task_id:fields.task.value.trim()};}
function included(){return [...document.querySelectorAll('[data-layer]:checked')].map(x=>x.dataset.layer);}
function status(message){$('status').textContent=message||'';}
async function request(path, method='GET', body){
  const response=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
  return data;
}
function renderFacts(layer,facts){
  const box=$(`${layer}-facts`);box.replaceChildren();
  const entries=Object.entries(facts);
  if(!entries.length){const empty=document.createElement('span');empty.className='empty';empty.textContent='Пока пусто';box.append(empty);return;}
  for(const [key,value] of entries){const tag=document.createElement('span');tag.className='fact';const bold=document.createElement('b');bold.textContent=`${key}: `;tag.append(bold,document.createTextNode(value));box.append(tag);}
}
function bubble(role,text){const item=document.createElement('div');item.className=`bubble ${role}`;item.textContent=text;$('chat').append(item);$('chat').scrollTop=$('chat').scrollHeight;}
function renderMemory(memory){
  renderFacts('short',memory.short.facts);renderFacts('working',memory.working);renderFacts('long',memory.long);
  $('short-count').textContent=`Реплик в диалоге: ${memory.short.messages.length}`;
  $('scope').textContent=`${fields.session.value} · ${fields.task.value}`;
  $('chat').replaceChildren();for(const m of memory.short.messages)bubble(m.role,m.content);
}
async function load(){
  const query=new URLSearchParams(ids());const data=await request(`/api/state?${query}`);renderMemory(data.memory);status('Загружены три слоя выбранного контекста.');
}
async function save(){
  const body={...ids(),layer:$('layer').value,key:$('key').value,value:$('value').value};
  const data=await request('/api/memory','POST',body);renderMemory(data.memory);status(`Факт «${body.key}» сохранён только в слой ${body.layer}.`);$('key').value='';$('value').value='';
}
function showContext(context){$('context').textContent=JSON.stringify(context,null,2);}
async function preview(){
  const data=await request('/api/preview','POST',{...ids(),text:$('prompt').value,include:included()});showContext(data.context);status('Показан точный состав запроса модели.');
}
async function ask(){
  const text=$('prompt').value.trim();if(!text){status('Введите вопрос.');return;}
  $('ask').disabled=true;status('Агент отвечает…');
  try{const data=await request('/api/chat','POST',{...ids(),text,include:included(),provider_id:$('provider').value});renderMemory(data.memory);showContext(data.context);$('prompt').value='';status(`Ответ: ${data.provider} / ${data.model}. В панели справа — использованная память.`);}
  finally{$('ask').disabled=false;}
}
function wire(id,fn){$(id).addEventListener('click',()=>fn().catch(error=>status(`Ошибка: ${error.message}`)));}
wire('load',load);wire('save',save);wire('preview',preview);wire('ask',ask);
$('prompt').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('ask').click();}});
load().catch(error=>status(`Ошибка: ${error.message}`));

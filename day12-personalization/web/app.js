const $=id=>document.getElementById(id);
const fields=['address','style','format','constraints','trigger'];
const user=()=> $('user').value.trim();
const scope=()=>({user_id:user(),session_id:$('session').value.trim(),task_id:'task-1'});
const profile=()=>({...Object.fromEntries(fields.map(key=>[key,$(key).value])),roles:$('roles').value.split(',').map(x=>x.trim()).filter(Boolean)});
function showProfile(value){for(const key of fields)$(key).value=value[key]||'';$('roles').value=value.roles.join(', ');}
function status(value){$('status').textContent=value;}
async function api(path,body){const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const data=await response.json();if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);return data;}
async function load(){const data=await api(`/api/profile?${new URLSearchParams({user_id:user()})}`);showProfile(data.profile);status(`Профиль ${user()} открыт.`);}
async function save(){const data=await api('/api/profile',{user_id:user(),profile:profile()});showProfile(data.profile);status(`Профиль ${user()} сохранён.`);}
async function saveMemory(){const key=$('memory-key').value,value=$('memory-value').value;const data=await api('/api/memory',{...scope(),key,value});$('memory-view').textContent=`Рабочая память: ${key} = ${data.memory.working[key]}`;status(`Факт задачи сохранён для ${user()}.`);}
async function preview(){const data=await api('/api/preview',{...scope(),text:$('prompt').value,provider_id:$('provider').value});$('context').textContent=JSON.stringify(data.context,null,2);status('Профиль включён в запрос автоматически.');}
async function ask(){const button=$('ask');button.disabled=true;status('Агент работает…');try{const data=await api('/api/chat',{...scope(),text:$('prompt').value,provider_id:$('provider').value});$('answer').textContent=data.answer;$('context').textContent=JSON.stringify(data.context,null,2);status(data.steps.length?`Роли выполнены по порядку: ${data.steps.map(x=>x.role).join(' → ')}`:'Обычный запрос с профилем.');}finally{button.disabled=false;}}
for(const [id,fn] of [['load',load],['save',save],['memory-save',saveMemory],['preview',preview],['ask',ask]])$(id).addEventListener('click',()=>fn().catch(error=>status(`Ошибка: ${error.message}`)));
load().catch(error=>status(`Ошибка: ${error.message}`));

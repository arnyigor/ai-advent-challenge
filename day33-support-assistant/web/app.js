'use strict';
const $ = selector => document.querySelector(selector);
const state = {tickets:[],ticket:null,context:null,items:[],filter:'all',busy:false,loading:false,selection:0};
window.demoState = {ready:false,answers:0};
function el(tag, className, text){const n=document.createElement(tag);if(className)n.className=className;if(text!==undefined)n.textContent=text;return n;}
function button(text, handler, className=''){const n=el('button',className,text);n.type='button';n.addEventListener('click',handler);return n;}
function notice(message){$('#notice').textContent=message;$('#notice').hidden=!message;}
async function api(url, options={}){
 const r=await fetch(url,options);let data;try{data=await r.json();}catch{throw new Error('Сервер вернул неожиданный ответ. Попробуйте обновить страницу.');}
 if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'Проверьте заполнение полей и повторите.');return data;
}
function showPage(page){for(const name of ['product','support']){$(`#${name}-page`).hidden=name!==page;$(`#nav-${name}`).classList.toggle('active',name===page);}$('body').dataset.page=page;}
$('#nav-product').addEventListener('click',()=>showPage('product'));
$('#nav-support').addEventListener('click',()=>showPage('support'));
$('#product-help').addEventListener('click',()=>openArticle('purchases'));
document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>document.getElementById(b.dataset.close).close()));
document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}}));
function localDate(){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Yekaterinburg'}).format(new Date());}
function openPurchase(){$('#purchase-error').textContent='';$('#purchase-form').reset();$('#purchase-form').elements.purchased.value=localDate();$('#purchase-dialog').showModal();$('#purchase-form').elements.name.focus();}
$('#add-purchase').addEventListener('click',openPurchase);
function formatDate(s){return new Date(s+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'});}
async function loadPurchases(){state.items=(await api('/api/purchases')).items;renderPurchases();}
function renderPurchases(){
 $('#stat-total').textContent=state.items.length;$('#stat-active').textContent=state.items.filter(i=>i.status!=='expired').length;$('#stat-soon').textContent=state.items.filter(i=>i.status==='soon').length;
 const container=$('#purchases');container.replaceChildren();const items=state.items.filter(i=>state.filter==='all'||i.status===state.filter);
 if(!items.length){const box=el('div','empty');box.append(el('div','purchase-symbol','◇'),el('h3','',state.items.length?'Здесь пока пусто':'Первая покупка — первый порядок.'),el('p','',state.items.length?'Покупок с таким сроком пока нет.':'Добавьте вещь и срок гарантии. Мы посчитаем дату окончания.'),button('＋ Добавить покупку',openPurchase,'button'));container.append(box);return;}
 for(const i of items){const card=el('article','purchase-card');card.dataset.purchaseId=i.id;
  card.append(el('span','purchase-symbol','◇'),el('span','status '+i.status,{active:'Активна',soon:'Истекает скоро',expired:'Истекла'}[i.status]),el('h3','',i.name),el('div','shop',i.store||'Магазин не указан'),el('div','expiry','До '+formatDate(i.expires)),el('div','remaining',i.days_left<0?'Гарантийный срок закончился':i.days_left===0?'Последний день гарантии':'Осталось дней: '+i.days_left));
  if(i.note)card.append(el('p','note',i.note));container.append(card);}
}
document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{state.filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(n=>n.classList.toggle('active',n===b));renderPurchases();}));
$('#purchase-form').addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget;const values=Object.fromEntries(new FormData(form));values.months=Number(values.months);$('#save-purchase').disabled=true;$('#purchase-error').textContent='';
 try{await api('/api/purchases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});$('#purchase-dialog').close();await loadPurchases();window.demoState.purchaseSaved=true;}catch(err){$('#purchase-error').textContent=err.message;}finally{$('#save-purchase').disabled=false;}
});
function renderTickets(){const container=$('#ticket-list');container.replaceChildren();const query=$('#ticket-search').value.toLocaleLowerCase('ru');
 const tickets=state.tickets.filter(t=>`${t.id} ${t.title} ${t.user_name} ${t.category}`.toLocaleLowerCase('ru').includes(query));
 if(!tickets.length)container.append(el('p','muted','Ничего не найдено. Попробуйте другое слово.'));
 for(const t of tickets){const node=button('',()=>selectTicket(t.id),'ticket'+(state.ticket?.id===t.id?' active':''));node.dataset.ticketId=t.id;node.disabled=state.busy;
 const top=el('div','ticket-top');top.append(el('span','',t.id),el('span','',t.category));const bottom=el('div','ticket-bottom');bottom.append(el('span','',t.user_name),el('span',t.priority==='high'?'priority':'',t.priority==='high'?'● Срочный':'Открыт'));node.append(top,el('strong','',t.title),bottom);container.append(node);}
 $('#ticket-count').textContent=state.tickets.length;
}
$('#ticket-search').addEventListener('input',renderTickets);
function traceText(trace){return JSON.stringify(trace,null,2);}
function renderContext(data){const c=$('#context');c.replaceChildren();const u=data.user,t=data.ticket;const card=el('section','user-card');card.append(el('div','eyebrow','ПОЛЬЗОВАТЕЛЬ'),el('div','user-avatar',u.name.split(' ').map(s=>s[0]).join('')),el('h3','',u.name),el('div','email',u.email),el('span','status','Аккаунт активен · демо'));c.append(card);
 const details=el('section','context-section');details.append(el('h3','','Контекст обращения'));
 for(const [k,v] of [['План',u.plan],['Способ входа',u.auth_method==='email_link'?'Ссылка из письма (демо)':'Браузерная сессия'],['Среда',t.environment]]){const row=el('div','key-value');row.append(el('span','',k),el('span','',v));details.append(row);}details.append(el('p','',t.description));c.append(details);
 const events=el('section','context-section');events.append(el('h3','','События тикета'));for(const event of t.events){const node=el('div','event');node.append(el('small','',event.at),el('p','',event.detail));events.append(node);}c.append(events);
 if(data.related_tickets.length){const related=el('section','context-section');related.append(el('h3','','Ещё у этого пользователя'));for(const r of data.related_tickets)related.append(button(r.id+' · '+r.title,()=>selectTicket(r.id),'source-link'));c.append(related);}
}
function userMessage(text){return el('div','message user',text);}
function answerMessage(answer){const box=el('article','message assistant');const label=el('div','answer-label');label.append(el('div','assistant-avatar','✦'),el('strong','','Ассистент СрокОК'),el('span','','по FAQ и тикету'));box.append(label);const body=el('div','answer-body');
 const used=[...new Set(answer.paragraphs.flatMap(p=>p.source_ids))];
 for(const p of answer.paragraphs){const n=el('p','',p.text);for(const id of p.source_ids){const s=answer.sources.find(s=>s.id===id);if(s){const cite=button('['+(used.indexOf(id)+1)+']',()=>openArticle(s.document_id),'citation');cite.title=s.section;n.append(document.createTextNode(' '),cite);}}body.append(n);}box.append(body);
 if(answer.needs_human)box.append(el('p','needs-human','Может потребоваться помощь человека. Автоматическая передача обращения не настроена.'));
 if(used.length){const details=el('details','answer-sources');details.append(el('summary','','Источники ответа · '+used.length));for(const id of used){const s=answer.sources.find(s=>s.id===id);if(s)details.append(button('['+(used.indexOf(id)+1)+'] '+s.section,()=>openArticle(s.document_id),'source-link'));}box.append(details);}
 const meta=el('div','answer-meta',`${answer.model} · ${Math.round(answer.elapsed_ms/100)/10} с · ${answer.mcp.server} · RAG ${answer.index_version}`);box.append(meta);return box;
}
function scrollChat(){const n=$('#chat');n.scrollTop=n.scrollHeight;}
function renderHistory(history){const chat=$('#chat');chat.replaceChildren();
 if(!history.length){const welcome=el('div','welcome');welcome.append(el('div','assistant-avatar','✦'),el('h3','','Я уже вижу контекст обращения.'),el('p','','Объясню, что произошло, и предложу шаги по документации. Источники можно открыть и проверить.'));const suggestions=el('div','suggestions');for(const text of [state.ticket.suggestion,'Что мне сделать дальше?'])suggestions.append(button(text,()=>{if(state.busy||state.loading)return;$('#message').value=text;$('#chat-form').requestSubmit();}));welcome.append(suggestions);chat.append(welcome);}
 else for(const m of history)chat.append(m.role==='user'?userMessage(m.content.text):answerMessage(m.content));scrollChat();
}
function updateInput(){const disabled=state.busy||state.loading||!state.context;$('#message').disabled=disabled;$('#send').disabled=disabled;$('#send').textContent=state.busy?'Готовим ответ…':'Отправить ↑';renderTickets();}
async function selectTicket(id){if(state.busy)return;const selected=state.tickets.find(t=>t.id===id);if(!selected)return;const seq=++state.selection;state.ticket=selected;state.context=null;state.loading=true;window.demoState.selected=id;$('#chat-error').hidden=true;$('#chat').replaceChildren(el('p','muted','Получаем контекст через MCP…'));$('#chat-heading').replaceChildren(el('small','',selected.id+' · '+selected.category),el('h2','',selected.title));updateInput();
 try{const data=await api('/api/tickets/'+encodeURIComponent(id));if(seq!==state.selection)return;state.context=data.context;renderContext(data.context);$('#mcp-trace').textContent=traceText(data.mcp);renderHistory(data.history);window.demoState.context=data.context;window.demoState.mcp=data.mcp;}catch(err){if(seq!==state.selection)return;$('#chat').replaceChildren(el('p','muted',err.message),button('Повторить загрузку',()=>selectTicket(id),'button secondary'));}finally{if(seq===state.selection){state.loading=false;updateInput();}}
}
$('#message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#chat-form').requestSubmit();}});
$('#chat-form').addEventListener('submit',async e=>{e.preventDefault();const message=$('#message').value.trim();if(!message||state.busy||state.loading||!state.context)return;state.busy=true;updateInput();$('#chat-error').hidden=true;const user=userMessage(message),pending=el('div','message pending','Читаю статьи и события обращения');$('#chat').append(user,pending);$('#message').value='';scrollChat();window.demoState.pending=true;
 try{const answer=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket_id:state.ticket.id,message})});pending.remove();$('#chat').append(answerMessage(answer));$('#mcp-trace').textContent=traceText(answer.mcp);window.demoState.answers++;window.demoState.lastAnswer=answer;scrollChat();}catch(err){pending.remove();user.remove();$('#message').value=message;$('#chat-error').textContent=err.message+' Вопрос сохранён в поле — можно повторить.';$('#chat-error').hidden=false;window.demoState.error=err.message;}finally{state.busy=false;window.demoState.pending=false;updateInput();$('#message').focus();}
});
async function openArticle(id){const dialog=$('#article-dialog');$('#article-title').textContent='База знаний';$('#article-body').replaceChildren(el('p','muted','Загружаем статью…'));if(!dialog.open)dialog.showModal();
 try{const data=await api('/api/knowledge/'+encodeURIComponent(id));$('#article-title').textContent=data.title;const container=$('#article-body');container.replaceChildren();const lines=data.text.split('\n');let paragraph=[];function flush(){if(paragraph.length){container.append(el('p','',paragraph.join('\n')));paragraph=[];}}
 for(const line of lines){if(line.startsWith('# '))continue;if(line.startsWith('## ')){flush();container.append(el('h3','',line.slice(3)));}else if(!line.trim()){flush();}else paragraph.push(line);}flush();window.demoState.article=id;
 }catch(err){$('#article-body').replaceChildren(el('p','form-error',err.message));}
}
async function init(){
 try{await loadPurchases();}catch(err){notice(err.message);}
 try{const data=await api('/api/bootstrap');state.tickets=data.tickets;renderTickets();$('#mcp-trace').textContent=traceText(data.mcp);for(const doc of data.knowledge)$('#knowledge-links').append(button(doc.title+' ↗',()=>openArticle(doc.id)));$('#index-label').textContent=`${data.index.chunks} разделов · BM25 · ${data.index.version}`;await selectTicket(state.tickets[0].id);window.demoState.ready=true;}catch(err){$('#ticket-list').replaceChildren(el('p','form-error',err.message),button('Повторить',()=>location.reload(),'button secondary'));notice('Поддержка: '+err.message);}
}
init();

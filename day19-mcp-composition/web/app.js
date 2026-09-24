const $=selector=>document.querySelector(selector);
const pretty=value=>JSON.stringify(value,null,2);
$('#run').addEventListener('click',async()=>{
  const button=$('#run');button.disabled=true;$('#status').textContent='Выполняется MCP-цепочка…';
  try{
    const response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:$('#query').value})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'Ошибка запроса');
    const digest=data.trace[1].result;$('#model').textContent=digest.mode==='model'?`Модель: ${digest.model} · реальный вызов Gemini`:`Без модели · ${digest.note}`;
    $('#handoff-items').textContent=`search → summarize: передано ${data.trace[0].result.items.length} материала; ID: ${data.trace[0].result.items.map(item=>item.id).join(', ')||'нет'}`;
    $('#handoff-summary').textContent=`summarize → saveToFile: передано ${digest.summary.length} символов сводки; режим: ${digest.mode}; модель: ${digest.model||'не использовалась'}`;
    const list=document.createElement('ul');
    for(const tool of data.catalog){const item=document.createElement('li');const name=document.createElement('strong');name.textContent=tool.name;const description=document.createElement('small');description.textContent=tool.description;item.append(name,description);list.append(item);}
    $('#catalog').replaceChildren(Object.assign(document.createElement('h2'),{textContent:`Каталог: ${data.server}`}),list);
    const heading=Object.assign(document.createElement('h2'),{textContent:'Трасса tools/call'});$('#trace').replaceChildren(heading);
    for(const [index,step] of data.trace.entries()){
      const card=document.createElement('article');card.className='call';const title=document.createElement('h3');title.textContent=`${index+1}. ${step.tool}`;
      const pair=document.createElement('div');pair.className='pair';
      for(const [label,value] of [['Аргументы',step.arguments],['Результат',step.result]]){const block=document.createElement('div');const h=document.createElement('h4');h.textContent=label;const pre=document.createElement('pre');pre.textContent=pretty(value);block.append(h,pre);pair.append(block);}
      card.append(title,pair);$('#trace').append(card);
    }
    $('#path').textContent=data.file;$('#content').textContent=data.content;$('#status').textContent='Цепочка выполнена · 3 вызова tools/call';
  }catch(error){$('#status').textContent=`Ошибка: ${error.message}`;}finally{button.disabled=false;}
});

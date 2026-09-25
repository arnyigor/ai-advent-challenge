const $=selector=>document.querySelector(selector);
function element(tag,text){const node=document.createElement(tag);node.textContent=text;return node;}
function explain(step){
  const a=step.arguments,r=step.result;
  switch(step.tool){
    case 'knowledge.search':return `Искали тему «${a.query}» в локальном корпусе. Найдено документов: ${r.ids.length}. Их ID: ${r.ids.join(', ')||'нет'}.`;
    case 'knowledge.read':return `По ID «${a.id}» прочитан документ «${r.title}». Его полный текст будет передан серверу analysis.`;
    case 'analysis.summarize':return `Получены ${a.items.length} документа с сервера knowledge. Сервер analysis собрал сводку из их текстов. Модель выбрала этот инструмент.`;
    case 'analysis.verify':return `Сводка сверена с исходными материалами. Результат: ${r.valid?'совпадает, можно сохранять':'проверка не пройдена'}.`;
    case 'storage.save':return `Проверенная сводка записана в новый TXT-файл. Следующий шаг — прочитать его обратно.`;
    case 'storage.read':return `TXT прочитан с диска. Агент сравнивает его содержимое с текстом, переданным при сохранении.`;
  }
}
$('#run').addEventListener('click',async()=>{
  $('#run').disabled=true;$('#status').textContent='Подключение трёх серверов и выполнение агента…';
  $('#trace').replaceChildren();$('#catalog').replaceChildren();$('#path').textContent='—';$('#content').textContent='—';$('#model-answer').textContent='—';
  try{
    const response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:$('#query').value})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'Ошибка запроса');
    $('#catalog').append(element('h2',`Каталог: ${data.servers.length} сервера · ${data.catalog.length} инструментов`));
    const list=element('ul','');
    for(const tool of data.catalog){const item=element('li','');item.append(element('strong',tool.name),element('small',tool.description));list.append(item);}
    $('#catalog').append(list);$('#trace').append(element('p',`Фактически использована модель: ${data.model}. Обращений к модели: ${data.model_turns}. Инструменты ниже выбраны моделью, затем вызваны через MCP.`));$('#trace').append(element('h2','Решения агента и реальные tools/call'));
    for(const [index,step] of data.trace.entries()){
      const card=element('article','');card.className='call';card.append(element('h3',`${index+1}. ${step.tool}`),element('p',`Выбор агента: ${step.reason}`));
      const pair=element('div','');pair.className='pair';
      for(const [label,value] of [['Аргументы',step.arguments],['Результат',step.result]]){const block=element('div','');block.append(element('h4',label),element('pre',JSON.stringify(value,null,2)));pair.append(block);}
      const explanation=element('p',explain(step));explanation.className='explanation';card.append(explanation);const details=element('details','');details.append(element('summary','Технические данные: аргументы и ответ MCP'),pair);card.append(details);$('#trace').append(card);
    }
    $('#model-answer').textContent=data.model_answer;$('#path').textContent=data.file?`${data.file} · запись проверена чтением`:'Файл не создавался';$('#content').textContent=data.content;
    $('#status').textContent=`Завершено · модель ${data.model} · ${data.trace.length} вызовов MCP · серверов: ${new Set(data.trace.map(step=>step.server)).size}`;
  }catch(error){$('#status').textContent=`Ошибка: ${error.message}`;}finally{$('#run').disabled=false;}
});

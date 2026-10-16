import {writeFile} from 'node:fs/promises';
import path from 'node:path';
export const STATUS_LABELS={blocked:'Заблокировано проверками',incomplete:'Недостаточно подтверждений',checks_passed_review_needed:'Проверки пройдены · требуется просмотр'};
export function escapeHtml(text) {return String(text??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])).replaceAll('\n','&#10;');}
export async function writeReport(run,dir) {
  const e=run.evidence,a=run.analysis;
  const intro=`# DnsHostsGenerator — материалы обновления\n\nСтатус: ${STATUS_LABELS[run.result_status]}.\n\nДиапазон: ${e.base_sha} → ${e.head_sha}.\nМодель: ${run.model||'генерация не завершена'}.\n\n`;
  const sources=e.sources.map(s=>`- [${s.id}] ${s.path} (${s.kind})`).join('\n');
  const checks=e.checks.map(c=>`- ${c.id}: ${c.status}; SHA ${c.tested_sha}`).join('\n');
  const notes=intro+(a?.release_notes||'AI-описание не получено. См. trace.json.')+`\n\n## Фактические проверки\n\n${checks}\n\nDebug APK не является production-публикацией в магазин.\n\n## Источники\n\n${sources}\n`;
  const testPlan=`# Рекомендуемые ручные проверки\n\nЭти сценарии предложены AI и не выполнены автоматически.\n\n`+
    (a?.manual_checks.map((c,i)=>`${i+1}. ${c.action}\n   Ожидается: ${c.expected_result}\n   Источники: ${c.evidence_ids.join(', ')}`).join('\n\n')||'Модель не вернула валидный тест-план.')+
    `\n\n## Неопределённость\n\n${a?.uncertainties.map(x=>'- '+x).join('\n')||'Нет завершённого анализа.'}\n`;
  const html=`<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>DnsHostsGenerator · отчёт</title><style>body{font:17px/1.6 system-ui;background:#f3f5f8;color:#142538;max-width:1050px;margin:40px auto;padding:24px}article,details{background:white;padding:24px;border-radius:16px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style><h1>DnsHostsGenerator</h1><p>${escapeHtml(STATUS_LABELS[run.result_status])}</p><article><pre>${escapeHtml(notes)}</pre></article><article><pre>${escapeHtml(testPlan)}</pre></article><h2>Проверяемые источники</h2>${e.sources.map(s=>`<details id="${s.id}"><summary>${escapeHtml(s.id+' · '+s.path)}</summary><pre>${escapeHtml(s.text)}</pre></details>`).join('')}</html>`;
  const artifacts={'evidence.json':JSON.stringify(e,null,2),'trace.json':JSON.stringify({id:run.id,events:run.events,error:run.error,model:run.model,usage:run.usage,result_status:run.result_status},null,2),
    'release-notes.md':notes,'test-plan.md':testPlan,'report.html':html};
  if(a)artifacts['analysis.json']=JSON.stringify(a,null,2);
  for(const [name,text] of Object.entries(artifacts))await writeFile(path.join(dir,name),text,'utf8');
  return Object.keys(artifacts);
}

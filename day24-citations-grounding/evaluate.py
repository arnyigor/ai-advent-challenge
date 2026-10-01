"""Ten real questions plus out-of-corpus probes; semantic verdicts are model assessments."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from rag_agent import RagAgent, DEFAULT_MODEL, validate_model_output, base
DAY = Path(__file__).resolve().parent
DEFAULT_QUESTIONS = DAY.parent / 'day22-first-rag-request/control_questions.json'
DEFAULT_REPORT = DAY / 'results/grounding.json'

def load_questions(path=DEFAULT_QUESTIONS):
    values = json.loads(Path(path).read_text(encoding='utf-8'))
    if len(values) != 10:
        raise ValueError('Нужны ровно 10 вопросов')
    return values

def audit_result(result):
    """Recheck the stored response against its own retrieved evidence."""
    chunks = {c['chunk_id']: c for c in result['retrieved_chunks']}
    model_valid = False
    if result.get('model_output'):
        try:
            validate_model_output(result['model_output'], [base.RetrievedChunk(**c) for c in chunks.values()])
            model_valid = result['model_output']['status'] == 'answered'
        except (ValueError, KeyError, TypeError):
            pass
    return {'has_sources': bool(result['sources']), 'has_quotes': bool(result['quotes']),
            'exact_quotes': bool(result['quotes']) and all(q['chunk_id'] in chunks and q['quote'] in chunks[q['chunk_id']]['text'] for q in result['quotes']),
            'meaning_supported': result['status'] == 'answered' and result['semantic_check']['supported'] is True,
            'source_metadata_valid': bool(result['sources']) and all(s['chunk_id'] in chunks and all(s[k] == chunks[s['chunk_id']][k] for k in ('source', 'section')) for s in result['sources']),
            'model_returns_required_fields': model_valid}

def audit_report(report):
    for row in report['items']:
        row['checks'] = audit_result(row['result'])
    for probe in report['probes']:
        r = probe['result']
        probe['passed'] = (r['status'] == 'unknown' and not r['sources'] and not r['quotes']
                           and 'не знаю' in r['answer'].casefold() and 'уточн' in r['answer'].casefold())
        probe['threshold_rule_passed'] = (r['reason'] != 'weak_context' or
            (all(c['score'] < r['similarity_threshold'] for c in r['candidates']) and r['prompt_chars'] == 0))
    report['summary'] = {k: sum(row['checks'][k] for row in report['items']) for k in report['items'][0]['checks']} | {
        'questions': len(report['items']), 'unknown': sum(row['result']['status'] == 'unknown' for row in report['items']),
        'probes_passed': sum(p['passed'] and p['threshold_rule_passed'] for p in report['probes'])}
    return report

def evaluate(agent, questions):
    items = []
    for question in questions:
        print(question['id'], flush=True)
        result = agent.ask(question['question'])
        checks = audit_result(result)
        items.append({**question, 'result': result, 'checks': checks})
    probes = []
    for q in ['Какой пароль администратора проекта Atlas?', 'Какова текущая цена акций Газпрома?']:
        result = agent.ask(q)
        probes.append({'question': q, 'result': result, 'passed': result['status'] == 'unknown' and not result['sources'] and not result['quotes']})
    return audit_report({'created_at': datetime.now(timezone.utc).isoformat(), 'model': agent.model,
            'settings': {'threshold': agent.similarity_threshold, 'top_k_before': agent.top_k_before, 'top_k_after': agent.top_k_after},
            'semantic_method': 'Separate LLM verification of each claim against its attached exact quotations; not a proof of truth.',
            'summary': {key: sum(row['checks'][key] for row in items) for key in items[0]['checks']} | {'questions': len(items), 'unknown': sum(row['result']['status'] == 'unknown' for row in items), 'probes_passed': sum(p['passed'] for p in probes)},
            'items': items, 'probes': probes})

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default=DEFAULT_MODEL)
    args = parser.parse_args()
    report = evaluate(RagAgent(model=args.model), load_questions())
    DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))

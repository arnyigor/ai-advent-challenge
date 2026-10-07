"""Explicit real-model benchmark. Never runs on application startup."""
import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from rag import DAY, ROOT, Pipeline, SYSTEM, token_budget


class CloudModel:
    def __init__(self, model):
        sys.path.insert(0, str(ROOT))
        from tools.llm.client import Client
        self.client = Client(model, quiet=True)
        self.model = model

    def generate(self, prompt):
        body = self.client.call(prompt, {'temperature': 0.1, 'maxOutputTokens': token_budget()},
                                system_instruction=SYSTEM)
        parts = body['candidates'][0]['content']['parts']
        answer = ''.join(p.get('text', '') for p in parts if not p.get('thought')).strip()
        if not answer:
            raise RuntimeError('Empty cloud answer')
        reason = body['candidates'][0].get('finishReason')
        return dict(answer=answer, model=self.model,
                    finish_reason={'STOP':'stop', 'MAX_TOKENS':'length'}.get(reason, reason),
                    usage=body.get('usageMetadata'))


def benchmark(pipeline, cases, providers, repeats, checkpoint=None):
    report = {'runs': [], 'summary': {}, 'generation_config': {'temperature':0.1,'max_tokens':token_budget()}, 'quality_note':
              'Номера ссылок и retrieval hit не доказывают смысл. Заполните manual_quality (0–2) и notes после сверки фактов.'}
    for case in cases:
        prepared = pipeline.prepare(case['query'])
        digest = hashlib.sha256(prepared['prompt'].encode()).hexdigest()
        for repeat in range(repeats):
            for name, provider in providers.items():
                row = dict(provider=name, repeat=repeat + 1, question=case['query'],
                           prompt_sha256=digest, retrieval_sec=prepared['retrieval_sec'],
                           retrieval_hit=any(s['source'] in case['relevant_sources'] for s in prepared['sources']),
                           manual_quality=None, notes='')
                call_started = time.perf_counter()
                try:
                    row.update(pipeline.answer(prepared, provider))
                    row['ok'] = True
                except Exception as exc:
                    row.update(ok=False, error=type(exc).__name__)
                    if hasattr(exc, 'metadata'):
                        row.update(exc.metadata)
                row['request_sec'] = round(time.perf_counter() - call_started, 4)
                report['runs'].append(row)
                if checkpoint:
                    checkpoint(report)
    for name in providers:
        rows = [r for r in report['runs'] if r['provider'] == name]
        valid = [r for r in rows if r['ok']]
        times = sorted(r['generation_sec'] for r in valid)
        report['summary'][name] = dict(requests=len(rows), successful=len(valid),
            success_rate=len(valid)/len(rows), median_generation_sec=statistics.median(times) if times else None,
            p95_generation_sec=times[max(0, math.ceil(.95*len(times))-1)] if times else None,
            truncated=sum(r.get('finish_reason') == 'length' for r in valid),
            cited_valid=sum(r['has_citations'] and r['citation_ids_valid'] for r in valid),
            exact_answer_consistency={q: len({r['answer'] for r in valid if r['question'] == q})
                                      for q in {r['question'] for r in rows}})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Explicitly enable inference')
    parser.add_argument('--cloud-model', help='Optional repository provider:model; sends retrieved context externally')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', default=str(DAY / 'results/comparison.json'))
    parser.add_argument('--cases', help='JSON query/relevant_sources benchmark cases')
    parser.add_argument('--retrieval', choices=('vector','hybrid'), default='hybrid')
    parser.add_argument('--top-k', type=int, default=6)
    args = parser.parse_args()
    if not args.run:
        parser.error('Use --run only when model is available')
    if not 1 <= args.repeats <= 10:
        parser.error('repeats must be 1..10')
    from pathlib import Path
    cases = json.loads((Path(args.cases) if args.cases else ROOT / 'day21-document-indexing/benchmark_queries.json').read_text(encoding='utf-8'))
    from rag import LocalModel
    providers = {'local': LocalModel()}
    if args.cloud_model:
        providers['cloud'] = CloudModel(args.cloud_model)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    def checkpoint(report):
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        row = report['runs'][-1]
        print(f"{len(report['runs'])}/{len(cases)*args.repeats*len(providers)} {row['provider']} ok={row['ok']} generation={row.get('generation_sec')}", flush=True)
    report = benchmark(Pipeline(retrieval=args.retrieval, top_k=args.top_k), cases, providers, args.repeats, checkpoint)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(target)

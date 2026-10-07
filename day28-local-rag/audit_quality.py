"""Attach saved reviews only to the exact answers that were reviewed."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def answer_hash(row):
    return hashlib.sha256(row.get('answer', '').encode()).hexdigest()


def audit(report, reviews):
    for row in report['runs']:
        matches = [r for r in reviews if r['question'] == row['question'] and
                   r['provider'] == row['provider'] and r['repeat'] == row['repeat'] and
                   r['answer_sha256'] == answer_hash(row) and
                   r['prompt_sha256'] == row['prompt_sha256']]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous exact-answer review')
        review = matches[0]
        if review['score'] not in (0, 1, 2):
            raise ValueError('Score must be 0..2')
        row['manual_quality'] = review['score']
        row['notes'] = review['notes']
    for provider, summary in report['summary'].items():
        rows = [r for r in report['runs'] if r['provider'] == provider]
        summary['quality_mean_0_to_2'] = round(statistics.mean(r['manual_quality'] for r in rows), 3)
        summary['quality_full_answers'] = sum(r['manual_quality'] == 2 for r in rows)
    report['review_method'] = 'Source inspection by Codex agent; subjective end-to-end 0–2 rubric, not independent blind human review. Answer and prompt hashes prevent applying these scores to other generations or contexts.'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('report')
    parser.add_argument('reviews')
    args = parser.parse_args()
    path = Path(args.report)
    report = audit(json.loads(path.read_text(encoding='utf-8')),
                   json.loads(Path(args.reviews).read_text(encoding='utf-8')))
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(path)

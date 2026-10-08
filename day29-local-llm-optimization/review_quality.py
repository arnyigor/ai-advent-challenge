"""Apply explicit per-case reviews only to matching answer/context hashes."""
import argparse
import json
from pathlib import Path
from benchmark import digest, save


def apply(report, reviews):
    mapping = {(r['profile'], r['repeat'], r['case_id']): r for r in report['runs']}
    for review in reviews:
        row = mapping[(review['profile'], review['repeat'], review['case_id'])]
        if (digest(row.get('answer', '')) != review['answer_sha256'] or
                row['prompt_sha256'] != review['prompt_sha256']):
            raise ValueError('Review hashes do not match')
        if review['score'] not in (0, 1, 2) or not review['notes'].strip():
            raise ValueError('Score 0/1/2 and notes required')
        row.update(manual_quality=review['score'], quality_notes=review['notes'])
    report['quality_reviewer'] = 'Explicit manual reviews; not an automatic semantic evaluator'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('report', type=Path)
    parser.add_argument('reviews', type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding='utf-8'))
    reviews = json.loads(args.reviews.read_text(encoding='utf-8'))
    save(args.report, apply(report, reviews))

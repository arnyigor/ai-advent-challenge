"""Use the selected, pinned Day 29 configuration with the existing local RAG."""
import argparse
import json
import math
from pathlib import Path
import sys

from benchmark import DAY, digest, generate
from rag import EmptyModelAnswer, LocalModel, Pipeline


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(config.get('system'), str) or not config['system'].strip():
        raise ValueError('Nonempty system prompt required')
    if digest(config['system']) != config.get('system_sha256'):
        raise ValueError('Selected system prompt hash mismatch')
    if not math.isfinite(config['temperature']) or not 0 <= config['temperature'] <= 2:
        raise ValueError('Temperature must be 0..2')
    if not isinstance(config['max_tokens'], int) or not 128 <= config['max_tokens'] <= 8192:
        raise ValueError('max_tokens must be 128..8192')
    return config


class ConfiguredModel:
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or LocalModel(config['url'], config['model'])

    def generate(self, prompt):
        result = generate(self.client, {'prompt': prompt}, self.config['profile'], self.config)
        if not result['ok']:
            raise EmptyModelAnswer({'finish_reason': result['finish_reason']}, {'usage': result['usage']})
        return result


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('question', nargs='?')
    parser.add_argument('--config', type=Path, default=DAY / 'optimized.json')
    parser.add_argument('--inspect', action='store_true', help='Configuration only; no model calls')
    parser.add_argument('--retrieve-only', action='store_true')
    args = parser.parse_args()
    config = load_config(args.config)
    if args.inspect:
        result = config
    elif args.question:
        pipeline = Pipeline()
        prepared = pipeline.prepare(args.question)
        result = prepared if args.retrieve_only else pipeline.answer(prepared, ConfiguredModel(config))
        result['selected_profile'] = config['profile']
        result['prompt_sha256'] = digest(prepared['prompt'])
    else:
        parser.error('Provide a question or --inspect')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

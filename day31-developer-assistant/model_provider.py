"""Explicit generation provider; embeddings and MCP remain local."""
import os
from pathlib import Path
import sys
import requests

from project_index import ROOT
from rag import LocalModel, token_budget


def settings():
    provider = os.environ.get('DAY31_LLM_PROVIDER', 'local').strip().lower()
    defaults = {'local': os.environ.get('LOCAL_LLM_MODEL', 'не настроена'),
                'openrouter': 'openrouter/free', 'gemini': 'gemini-3.5-flash-lite'}
    if provider not in defaults:
        raise ValueError('DAY31_LLM_PROVIDER: local, openrouter or gemini')
    return provider, os.environ.get('DAY31_LLM_MODEL', defaults[provider])


class CloudModel:
    def __init__(self, provider, model, system):
        self.provider, self.model, self.system = provider, model, system
        if provider == 'openrouter' and model != 'openrouter/free' and not model.endswith(':free'):
            raise ValueError('OpenRouter accepts only openrouter/free or a :free model')

    def generate(self, prompt):
        if self.provider == 'gemini':
            root = str(Path(__file__).resolve().parents[1])
            if root not in sys.path:
                sys.path.insert(0, root)
            from tools.llm.client import Client
            from tools.llm.gemini import extract_response, extract_usage
            data = Client('gemini:' + self.model, quiet=True).call(prompt,
                {'temperature': 0.1, 'maxOutputTokens': token_budget()},
                system_instruction=self.system)
            result = extract_response(data)
            if not result['text'].strip():
                raise RuntimeError('Gemini returned no answer')
            reason = result['finish_reason']
            return {'answer': result['text'].strip(), 'model': 'gemini:' + self.model,
                    'finish_reason': 'length' if reason == 'MAX_TOKENS' else reason.lower() if reason else None,
                    'usage': extract_usage(data)}
        key = os.environ.get('OPENROUTER_API_KEY', '').strip()
        if not key:
            raise ValueError('OPENROUTER_API_KEY is not set')
        try:
            response = requests.post('https://openrouter.ai/api/v1/chat/completions',
                headers={'Authorization': 'Bearer ' + key},
                json={'model': self.model, 'messages': [{'role': 'system', 'content': self.system},
                    {'role': 'user', 'content': prompt}], 'temperature': 0.1,
                    'max_tokens': token_budget(), 'stream': False}, timeout=90,
                allow_redirects=False)
        except requests.RequestException:
            raise RuntimeError('OpenRouter network error') from None
        if response.status_code != 200:
            raise RuntimeError(f'OpenRouter HTTP {response.status_code}; no paid fallback')
        body = response.json()
        choice = body['choices'][0]
        answer = choice['message'].get('content')
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError('OpenRouter returned no answer')
        return {'answer': answer.strip(), 'model': 'openrouter:' + body.get('model', self.model),
                'finish_reason': choice.get('finish_reason'), 'usage': body.get('usage')}


def create_model(system):
    provider, model = settings()
    return LocalModel(system=system) if provider == 'local' else CloudModel(provider, model, system)

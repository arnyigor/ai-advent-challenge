"""Провайдер генерации: Gemini (бесплатный tier) или локальный OpenAI-совместимый
сервер или OpenRouter :free. Образец — day31 model_provider.py; embeddings не нужны."""
import os
from pathlib import Path
import sys

import requests


def settings():
    provider = os.environ.get('DAY34_LLM_PROVIDER', 'gemini').strip().lower()
    defaults = {'gemini': 'gemini-3.5-flash-lite',
                'local': os.environ.get('LOCAL_LLM_MODEL', 'не настроена'),
                'openrouter': 'openrouter/free'}
    if provider not in defaults:
        raise ValueError('DAY34_LLM_PROVIDER: gemini, local или openrouter')
    return provider, os.environ.get('DAY34_LLM_MODEL', defaults[provider])


def token_budget():
    return int(os.environ.get('DAY34_MAX_TOKENS', '1600'))


class ChatModel:
    """Единый интерфейс: generate(system, prompt) -> {'answer', 'model', ...}."""

    def __init__(self, provider, model):
        self.provider, self.model = provider, model
        if provider == 'openrouter' and model != 'openrouter/free' and not model.endswith(':free'):
            raise ValueError('OpenRouter принимает только openrouter/free или модель :free')

    @property
    def label(self):
        return f'{self.provider}:{self.model}'

    def generate(self, system, prompt):
        if self.provider == 'gemini':
            root = str(Path(__file__).resolve().parents[1])
            if root not in sys.path:
                sys.path.insert(0, root)
            from tools.llm.client import Client
            from tools.llm.gemini import extract_response, extract_usage
            data = Client('gemini:' + self.model, quiet=True).call(prompt,
                {'temperature': 0.1, 'maxOutputTokens': token_budget()},
                system_instruction=system)
            result = extract_response(data)
            if not result['text'].strip():
                raise RuntimeError('Gemini вернул пустой ответ')
            return {'answer': result['text'].strip(), 'model': 'gemini:' + self.model,
                    'usage': extract_usage(data)}
        if self.provider == 'openrouter':
            key = os.environ.get('OPENROUTER_API_KEY', '').strip()
            if not key:
                raise ValueError('OPENROUTER_API_KEY не задан')
            url = 'https://openrouter.ai/api/v1/chat/completions'
        else:
            key = None
            url = os.environ.get('LOCAL_LLM_URL', 'http://127.0.0.1:8085/v1').rstrip('/') + '/chat/completions'
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        try:
            response = requests.post(url, headers=headers,
                json={'model': self.model,
                      'messages': [{'role': 'system', 'content': system},
                                   {'role': 'user', 'content': prompt}],
                      'temperature': 0.1, 'max_tokens': token_budget(), 'stream': False},
                timeout=180, allow_redirects=False)
        except requests.RequestException:
            raise RuntimeError(f'{self.provider}: сетевая ошибка') from None
        if response.status_code != 200:
            raise RuntimeError(f'{self.provider}: HTTP {response.status_code}; платного fallback нет')
        body = response.json()
        choice = body['choices'][0]
        answer = choice['message'].get('content')
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError(f'{self.provider}: пустой ответ')
        return {'answer': answer.strip(), 'model': f"{self.provider}:{body.get('model', self.model)}",
                'usage': body.get('usage')}


def create_model():
    provider, model = settings()
    return ChatModel(provider, model)

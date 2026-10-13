"""Submit existing ComfyUI QwenTTS Voice Design nodes; save genuine audio."""
import argparse
import json
from pathlib import Path
import time
import requests

DAY = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8188')
    parser.add_argument('--submit', action='store_true')
    args = parser.parse_args()
    if not args.submit:
        parser.print_help()
        return
    spec = json.loads((DAY / 'narration.json').read_text(encoding='utf-8'))
    graph = {}
    for i, scene in enumerate(spec['scenes']):
        voice, save = str(2*i+1), str(2*i+2)
        graph[voice] = {'class_type': 'AILab_Qwen3TTSVoiceDesign_Advanced', 'inputs': {
            'text': scene['text'], 'instruct': spec['voice_description'], 'model_size': '1.7B',
            'device': 'cuda', 'precision': 'bf16', 'language': 'Russian', 'max_new_tokens': 2048,
            'do_sample': True, 'top_p': .9, 'top_k': 50, 'temperature': .7,
            'repetition_penalty': 1.05, 'attention': 'sdpa', 'unload_models': False, 'seed': 313131}}
        graph[save] = {'class_type': 'SaveAudio', 'inputs': {'audio': [voice,0],
            'filename_prefix': 'day31/narration-' + scene['id']}}
    submitted = requests.post(args.url + '/prompt', json={'prompt': graph}, timeout=15)
    submitted.raise_for_status()
    result = submitted.json()
    out = DAY / 'video-frames' / 'narration'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'workflow-api.json').write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    prompt_id = result['prompt_id']
    print('ComfyUI prompt:', prompt_id, flush=True)
    record = {'prompt_id': prompt_id, 'node': 'AILab_Qwen3TTSVoiceDesign_Advanced', 'scenes': []}
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        history = requests.get(args.url + '/history/' + prompt_id, timeout=10).json().get(prompt_id)
        if history and history.get('status', {}).get('status_str') == 'error':
            (out / 'error.json').write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding='utf-8')
            raise RuntimeError('QwenTTS generation failed; see video-frames/narration/error.json')
        if history and history.get('status', {}).get('completed'):
            for i, scene in enumerate(spec['scenes']):
                item = history['outputs'][str(2*i+2)]['audio'][0]
                response = requests.get(args.url + '/view', params=item, timeout=30)
                response.raise_for_status()
                path = out / (scene['id'] + Path(item['filename']).suffix)
                path.write_bytes(response.content)
                record['scenes'].append({**scene, 'audio': str(path.resolve()), 'comfy_output': item})
            (DAY / 'evidence' / 'narration-generation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            print('Saved 5 real QwenTTS audio clips', flush=True)
            return
        time.sleep(2)
    raise TimeoutError('ComfyUI narration timed out')


if __name__ == '__main__':
    main()

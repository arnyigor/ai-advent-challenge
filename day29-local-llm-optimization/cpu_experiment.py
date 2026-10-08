"""Own CPU-only llama-server lifecycle; never terminate existing servers."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import psutil
import benchmark as bench
from rag import NoRedirect
from download_quants import DIRECTORY, HASHES, file_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--quants', nargs='+', choices=HASHES, default=list(HASHES))
    parser.add_argument('--profiles', nargs='+', choices=bench.PROFILES, default=['baseline'])
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--context', type=int, default=8192)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--port', type=int, default=8081)
    parser.add_argument('--label', default='quant-pilot')
    parser.add_argument('--case-ids', nargs='+', type=int, help='Optional screening subset; final comparison should use all cases')
    parser.add_argument('--reasoning', choices=['off', 'on'], default='off')
    parser.add_argument('--reasoning-budget', type=int, default=512, help='Used only with --reasoning on')
    parser.add_argument('--smoke-ask', action='store_true', help='Exercise ask.py against own server instead of running benchmark')
    args = parser.parse_args()
    if not args.run:
        print('No processes started. Use --run after benchmark.py --prepare.')
        return
    if args.repeats < 1 or args.context < 1024 or args.threads < 1 or args.reasoning_budget < 0:
        parser.error('Invalid repeats/context/threads')
    if Path(args.label).name != args.label or args.label in ('.', '..'):
        parser.error('label must be a filename component')
    cases = json.loads((bench.DAY / 'results/frozen.json').read_text(encoding='utf-8'))
    if args.smoke_ask:
        from ask import load_config
        selected = load_config(bench.DAY / 'optimized.json')
        if (args.quants != [selected['quantization']] or args.context != selected['context_window']
                or args.reasoning != selected['reasoning'] or args.threads != selected['threads']):
            parser.error('Smoke server settings must match optimized.json')
    if args.case_ids:
        unknown = set(args.case_ids) - {case['id'] for case in cases}
        if unknown:
            parser.error(f'Unknown case IDs: {sorted(unknown)}')
        cases = [case for case in cases if case['id'] in args.case_ids]
    server = os.environ.get('LLAMA_SERVER', 'G:/AIModels/llamacpp/llama-win-cuda-12.4-x64/llama-server.exe')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for quant in args.quants:
        model = DIRECTORY / f'Qwen3-1.7B-{quant}.gguf'
        if file_hash(model) != HASHES[quant]:
            raise ValueError(f'Unexpected weights: {model}')
        # Bind check: refuse to use or kill an unrelated listener.
        with socket.socket() as check:
            check.bind(('127.0.0.1', args.port))
        target = bench.DAY / 'results' / f'{args.label}-{quant}.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f'Choose a new --label; preserving {target}')
        command = [server, '-m', str(model), '--device', 'none', '--gpu-layers', '0',
            '--no-kv-offload', '--no-op-offload', '--ctx-size', str(args.context),
            '--parallel', '1', '--threads', str(args.threads), '--host', '127.0.0.1',
            '--port', str(args.port), '--alias', 'day29-qwen3-cpu', '--reasoning', args.reasoning,
            '--no-cache-prompt', '--no-context-shift', '--metrics']
        if args.reasoning == 'on':
            command.extend(['--reasoning-budget', str(args.reasoning_budget)])
        stop = threading.Event()
        samples = []
        with target.with_suffix('.log').open('w', encoding='utf-8') as log:
            started = time.perf_counter()
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            monitor = psutil.Process(process.pid)
            def sample():
                monitor.cpu_percent(None)
                while not stop.wait(0.25):
                    try:
                        samples.append(dict(rss=monitor.memory_info().rss, cpu_percent=monitor.cpu_percent(None)))
                    except psutil.Error:
                        return
            worker = threading.Thread(target=sample, daemon=True)
            worker.start()
            try:
                deadline = time.monotonic() + 180
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('llama-server exited; inspect log')
                    try:
                        with opener.open(f'http://127.0.0.1:{args.port}/health', timeout=2) as response:
                            if json.load(response).get('status') == 'ok':
                                break
                    except (OSError, ValueError):
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError('Server readiness timeout')
                    time.sleep(0.5)
                load_sec = time.perf_counter() - started
                client = bench.LocalModel(f'http://127.0.0.1:{args.port}/v1', 'day29-qwen3-cpu')
                if args.smoke_ask:
                    result = subprocess.run([sys.executable, str(bench.DAY / 'ask.py'), cases[0]['prepared']['question']],
                        capture_output=True, encoding='utf-8', timeout=180, check=True)
                    answer = json.loads(result.stdout)
                    if answer['prompt_sha256'] != cases[0]['prompt_sha256']:
                        raise ValueError('CLI retrieval differs from frozen context')
                    bench.save(bench.DAY / 'results/ask-smoke.json', answer)
                    bench.save(target, dict(command=command, server_load_sec=load_sec, smoke_result=answer))
                    print('Selected-config CLI smoke completed', flush=True)
                    continue
                # Same non-scored warmup; cache is disabled for measured calls.
                bench.generate(client, {'prompt': 'КОНТЕКСТ:\n[1] Код Atlas ORBIT-47.\nВОПРОС:\nКакой код Atlas?'}, 'prompt')
                samples.clear()
                metadata = dict(command=command, quantization=quant, weight_sha256=HASHES[quant],
                    file_bytes=model.stat().st_size, server_load_sec=load_sec, context_window=args.context,
                    reasoning=args.reasoning, reasoning_budget=args.reasoning_budget if args.reasoning == 'on' else None,
                    prompt_cache=False, cpu_resource_scope='llama-server process; sampled 250ms; CPU can exceed 100%',
                    frozen_cases=cases)
                def checkpoint(report):
                    report['metadata']['resources'] = dict(sampled_peak_rss_bytes=max((s['rss'] for s in samples), default=None),
                        mean_cpu_percent=sum(s['cpu_percent'] for s in samples)/len(samples) if samples else None,
                        sample_count=len(samples))
                    bench.save(target, report)
                cursor = [0]
                def observe(event, row):
                    if event == 'start':
                        cursor[0] = len(samples)
                    else:
                        measured = samples[cursor[0]:]
                        row['cpu_resources'] = dict(
                            sampled_peak_rss_bytes=max((s['rss'] for s in measured), default=None),
                            mean_cpu_percent=sum(s['cpu_percent'] for s in measured)/len(measured) if measured else None,
                            sample_count=len(measured))
                bench.run(cases, args.profiles, args.repeats, client, checkpoint, metadata, observe)
                print(target, flush=True)
            finally:
                stop.set()
                worker.join(timeout=2)
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()

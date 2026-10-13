"""Transcribe generated narration with an existing local Whisper model for QA."""
import argparse
import difflib
import json
from pathlib import Path
import re

DAY = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--whisper-model', type=Path, default=Path.home() / '.cache/whisper/large-v3-turbo.pt')
    args = parser.parse_args()
    if not args.whisper_model.is_file():
        raise FileNotFoundError('Specify a cached Whisper .pt file; no auto-download')
    import whisper
    model = whisper.load_model(str(args.whisper_model), device='cuda')
    record = json.loads((DAY / 'evidence/narration-generation.json').read_text(encoding='utf-8'))
    checked = []
    normal = lambda s: re.sub(r'[^\w]+', ' ', s.casefold()).strip()
    for scene in record['scenes']:
        result = model.transcribe(scene['audio'], language='ru', condition_on_previous_text=False)
        text = result['text'].strip()
        ratio = difflib.SequenceMatcher(None, normal(scene['text']), normal(text)).ratio()
        checked.append({'id':scene['id'], 'expected':scene['text'], 'transcribed':text,
                        'similarity':round(ratio,3)})
        print(scene['id'], text, flush=True)
    (DAY / 'evidence/narration-asr.json').write_text(json.dumps(checked,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()

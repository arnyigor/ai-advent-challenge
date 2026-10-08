"""Download pinned siblings of the existing Q4_K_M; verify every SHA-256."""
import hashlib
import json
from pathlib import Path
from huggingface_hub import hf_hub_download

REPO = 'unsloth/Qwen3-1.7B-GGUF'
REVISION = 'd7f544eead698dbd1f15126ef60b45a1e1933222'
DIRECTORY = Path('G:/AIModels/SmallAgents/Qwen3-1.7B')
HASHES = {
    'Q2_K': '62b3fb705434cb57fabc59d59aa7b4c6fb558fff7c7c4b2ce67456373bc30fd3',
    'Q4_K_M': 'b139949c5bd74937ad8ed8c8cf3d9ffb1e99c866c823204dc42c0d91fa181897',
    'Q8_0': '0becaa825564295d82e9af4d008bca5f8b7f5f73bf1c6a0b58f7c53ef26b47fd',
}


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    manifest = []
    for quant, expected in HASHES.items():
        name = f'Qwen3-1.7B-{quant}.gguf'
        target = DIRECTORY / name
        if not target.exists():
            hf_hub_download(REPO, name, revision=REVISION, local_dir=DIRECTORY)
        actual = file_hash(target)
        if actual != expected:
            raise ValueError(f'Hash mismatch: {name}; existing file preserved')
        manifest.append(dict(quantization=quant, path=str(target), bytes=target.stat().st_size,
            sha256=actual, repo=REPO, revision=REVISION))
        print(f'{quant}: SHA-256 verified', flush=True)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()

"""Package only explicit source directories; no database, credentials or browser profile."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from settings import DAY, DATA


def main():
    files = [p for p in DAY.iterdir() if p.is_file() and
        (p.suffix in {'.py', '.md', '.txt', '.json', '.mjs'} or p.name == '.gitignore')]
    for name in ['web', 'knowledge', 'fixtures', 'deploy']:
        files.extend(p for p in (DAY / name).rglob('*') if p.is_file() and
            p.suffix in {'.py', '.sh', '.md', '.js', '.css', '.html', '.svg', '.json'})
    shared = DAY.parent / 'day18-rss-scheduler' / 'day18_providers.py'
    files.append(shared)
    files.append(DAY.parent / 'tests' / 'test_day33_support.py')
    files.extend(p for p in (DAY / 'evidence').iterdir() if p.is_file() and p.suffix in {'.md', '.json', '.png'})
    DATA.mkdir(parents=True, exist_ok=True)
    target = DATA / 'code.zip'
    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        for file in sorted(files):
            archive.write(file, str(file.relative_to(DAY.parent)))
    print(f'{len(files)} source files packaged: {target}')


if __name__ == '__main__':
    main()

"""Small corpus RAG: section chunks + BM25, no heavyweight ML runtime."""
import hashlib
import math
import re
from collections import Counter
from settings import KNOWLEDGE

ALIASES = {'авторизац': 'вход', 'авторизаци': 'вход', 'логин': 'вход',
           'залогин': 'вход', 'войти': 'вход', 'вход': 'вход',
           'исчез': 'пропал', 'исчезл': 'пропал', 'пропал': 'пропал',
           'скача': 'экспорт', 'выгруз': 'экспорт', 'экспорт': 'экспорт',
           'гаранти': 'гарант', 'гарант': 'гарант', 'почт': 'email', 'письм': 'email'}
STOP = set('почему как что это мне моя мои мой меня где или для при есть про ещё него его она они оно уже какой какая будет можно нужно работает работать не да и в на с по к у а из до от но ли за то я вы мы он'.split())


def tokens(text):
    words = re.findall(r'[a-zа-я0-9_]+', text.lower().replace('ё', 'е'))
    result = []
    for word in words:
        if word in STOP or len(word) < 3:
            continue
        for prefixes, canonical in [(('экспорт', 'выгруз', 'скача'), 'экспорт'),
                (('авториза', 'войти', 'логин'), 'вход'),
                (('исчез', 'пропал'), 'пропал'), (('гарант',), 'гарант')]:
            if word.startswith(prefixes):
                word = canonical
                break
        # A deliberately small stemmer; BM25, not semantic embeddings.
        if re.search('[а-я]', word):
            word = re.sub(r'(иями|ами|ого|ему|ыми|ая|ый|ой|ую|ые|ий|ов|ам|ом|ах|ать|ить|ет|ют|ла|ли|ы|а|я|и|у|е)$', '', word)
        result.append(ALIASES.get(word, word))
    return result


class Index:
    def __init__(self, directory=KNOWLEDGE):
        self.documents, self.chunks = {}, []
        digest = hashlib.sha256()
        for path in sorted(directory.glob('*.md')):
            text = path.read_text(encoding='utf-8')
            digest.update(path.name.encode() + text.encode())
            title = text.splitlines()[0].lstrip('# ')
            self.documents[path.stem] = {'id': path.stem, 'title': title, 'text': text}
            for n, part in enumerate(re.split(r'\n## ', text)[1:], 1):
                heading, _, body = part.partition('\n')
                self.chunks.append({'id': f'{path.stem}-{n}', 'document_id': path.stem,
                    'title': title, 'section': heading, 'text': body.strip(),
                    'url': f'/api/knowledge/{path.stem}'})
        if not self.chunks:
            raise RuntimeError('База знаний пуста')
        self.version = digest.hexdigest()[:12]
        self.counts = [Counter(tokens(c['section'] + ' ' + c['text'])) for c in self.chunks]
        self.avg = sum(sum(c.values()) for c in self.counts) / len(self.counts)
        self.df = Counter(t for c in self.counts for t in c)

    def search(self, question, context='', limit=4):
        primary = set(tokens(question))
        generic_followup = any(t.startswith(('дальш', 'подроб', 'объясн', 'повтор', 'сдел')) for t in primary)
        if primary and not (primary & set(self.df)) and not generic_followup:
            return []
        expanded = primary | set(tokens(context))
        if not primary:
            expanded = set(tokens(context))
        ranked = []
        for chunk, counts in zip(self.chunks, self.counts):
            score = 0
            for term in expanded:
                freq = counts.get(term, 0)
                if freq:
                    idf = math.log(1 + (len(self.chunks) - self.df[term] + .5) / (self.df[term] + .5))
                    score += idf * freq * 2.5 / (freq + 1.5 * (.25 + .75 * sum(counts.values()) / self.avg)) * (2 if term in primary else .35)
            if score:
                ranked.append(dict(chunk, score=round(score, 3)))
        ranked.sort(key=lambda c: c['score'], reverse=True)
        return ranked[:limit]

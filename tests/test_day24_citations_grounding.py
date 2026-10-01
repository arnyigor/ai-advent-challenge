"""Evidence validation, retries, semantic rejection and threshold boundaries."""
import importlib.util
from pathlib import Path
import sys
import json
import pytest
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('day24_agent', ROOT / 'day24-citations-grounding/rag_agent.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
chunk = m.base.RetrievedChunk(1, 'real', 'handbook.md', 'Atlas', 'Safety', .83, 'ORBIT-47 используют только после подтверждения оператора.')
def payload(quote=chunk.text, cid='real'):
    return {'status':'answered', 'answer':'ORBIT-47 только после подтверждения оператора.',
            'sources':[{'source':chunk.source,'section':chunk.section,'chunk_id':cid}],
            'quotes':[{'claim':1,'chunk_id':cid,'quote':quote}],
            'claims':[{'text':'ORBIT-47 только после подтверждения оператора.', 'evidence':[{'chunk_id':cid,'quote':quote}]}]}
class Model:
    def __init__(self, values): self.values=iter(values); self.calls=[]
    def call(self, prompt, *args, **kwargs): self.calls.append(prompt); return json.dumps(next(self.values), ensure_ascii=False)
def agent(values, score=.83):
    a=object.__new__(m.RagAgent)
    a.llm=Model(values);a.model='fake';a.embedding_model='fake';a.top_k_before=8;a.top_k_after=4;a.similarity_threshold=.83
    a.rewrite_query=lambda q:(q,False)
    from dataclasses import replace
    a.retrieve=lambda q,top_k:[replace(chunk,score=score)]
    return a
check={'supported':True,'reason':'Условие разрешения совпадает с цитатой.','unsupported_claims':[]}
def test_exact_evidence():
    sources,quotes=m.validate_payload(payload(),[chunk]);assert sources[0]['source']=='handbook.md';assert quotes[0]['claim']==1
@pytest.mark.parametrize('value',[payload('выдуманная цитата'),payload(cid='invented'), {'status':'answered','claims':[]}, {'status':'answered','claims':[{'text':'x','evidence':[]}]}, {'status':'unknown','claims':[{}]}])
def test_reject_invalid(value):
    with pytest.raises(ValueError):m.validate_payload(value,[chunk])
def test_threshold_boundary_and_verified_answer():
    a=agent([payload(),check]);r=a.ask('Код Atlas?');assert r['status']=='answered';assert len(r['sources'])==len(r['quotes'])==1
    a=agent([],score=.8299);r=a.ask('Код?');assert r['status']=='unknown';assert r['reason']=='weak_context';assert not a.llm.calls;assert not r['sources'];assert 'Уточните' in r['answer']
def test_one_repair():
    a=agent([payload('fake'),payload(),check]);r=a.ask('Код?');assert r['status']=='answered';assert r['attempts']==2;assert len(r['validation_errors'])==1
def test_semantic_rejection():
    bad={'supported':False,'reason':'Условие не подтверждено','unsupported_claims':[1]}
    a=agent([payload(),bad,payload(),bad]);r=a.ask('Код?');assert r['status']=='unknown';assert r['sources']==r['quotes']==[];assert len(a.llm.calls)==4
def test_model_unknown():
    r=agent([{'status':'unknown','answer':'Не знаю. Уточните вопрос.', 'sources':[], 'quotes':[], 'claims':[]}]).ask('Пароль?');assert r['reason']=='insufficient_evidence'

@pytest.mark.parametrize('field',['answer','sources','quotes'])
def test_model_must_return_each_required_field(field):
    value=payload();value.pop(field)
    with pytest.raises(ValueError):m.validate_model_output(value,[chunk])

def test_model_cannot_add_uncited_answer_or_fake_metadata():
    value=payload();value['answer']+=' Пароль 1234.'
    with pytest.raises(ValueError):m.validate_model_output(value,[chunk])
    value=payload();value['sources'][0]['source']='invented.md'
    with pytest.raises(ValueError):m.validate_model_output(value,[chunk])
    value=payload();value['quotes'][0]['quote']='fake'
    with pytest.raises(ValueError):m.validate_model_output(value,[chunk])

def test_web_api(tmp_path):
    import threading
    import urllib.request
    day=ROOT / 'day24-citations-grounding'
    # Import server with its own script-style dependencies, without collection collisions.
    specs={}
    previous={name:sys.modules.get(name) for name in ('rag_agent','evaluate')}
    sys.modules['rag_agent']=m
    evspec=importlib.util.spec_from_file_location('evaluate',day/'evaluate.py')
    ev=importlib.util.module_from_spec(evspec);sys.modules['evaluate']=ev;evspec.loader.exec_module(ev)
    ss=importlib.util.spec_from_file_location('day24_server',day/'web_server.py')
    server_module=importlib.util.module_from_spec(ss);ss.loader.exec_module(server_module)
    for name,value in previous.items():
        if value is None:sys.modules.pop(name,None)
        else:sys.modules[name]=value
    server=server_module.create_server(agent=agent([payload(),check]));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        url=f'http://127.0.0.1:{server.server_port}'
        request=urllib.request.Request(url+'/api/ask',data=json.dumps({'question':'Код?'}).encode(),headers={'Content-Type':'application/json','Origin':url})
        with urllib.request.urlopen(request) as response:result=json.load(response)
        assert result['status']=='answered';assert result['quotes'][0]['chunk_id']=='real'
    finally:
        server.shutdown();server.server_close();thread.join(2)

def test_lexical_retrieval_adds_missing_vector_candidate(tmp_path,monkeypatch):
    from day21_pipeline import build_indexes
    from embeddings import HashEmbedder
    import index_store
    corpus=tmp_path/'corpus';corpus.mkdir()
    text='RSS articles collect INSERT OR IGNORE unique identifier'
    (corpus/'store.md').write_text('# Storage\n\n'+text,encoding='utf-8')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'repo_root':'.','sources':[{'root':'corpus','include':['*.md']}]}),encoding='utf-8')
    embedder=HashEmbedder(64)
    build_indexes(strategy='structure',manifest_path=manifest,index_dir=tmp_path/'indexes',model_name=embedder.name,embedder=embedder)
    a=m.RagAgent(index_path=tmp_path/'indexes/structure.sqlite3',embedder=embedder,llm=Model([]))
    monkeypatch.setattr(index_store,'search',lambda *_args,**_kwargs:[])
    found=a.retrieve('INSERT OR IGNORE',top_k=8)
    assert len(found)==1 and 'INSERT OR IGNORE' in found[0].text
    assert a._retrieval_channels[found[0].chunk_id]==['lexical']
    # Lexical hits carry real cosine, so the existing threshold can reject them.
    assert -1<=found[0].score<=1
    a.rewrite_query=lambda q:(q,False);a.similarity_threshold=1.0
    result=a.ask('INSERT OR IGNORE')
    assert result['reason']=='weak_context' and not a.llm.calls

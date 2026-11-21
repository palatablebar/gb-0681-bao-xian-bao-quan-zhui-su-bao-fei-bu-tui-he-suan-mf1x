from app.config import MODULES

def test_all_module_apis(client):
    for mod,_ in MODULES:assert client.get('/api/'+mod).status_code==200
def test_all_module_pages(client):
    for mod,_ in MODULES:assert client.get('/'+mod).status_code==200
def test_run_and_export(client):
    r=client.post('/api/runs',json={'sample':'dirty.csv'});assert r.status_code==200
    s=r.get_json()
    # 再保调整必须全部归属后才允许结案下载
    sync=client.post('/api/m8_cession/sync',json={});assert sync.status_code==200
    from app.modules.m8_cession.rules import CURRENT_OFFSET
    for adj in sync.get_json()['snapshot']['adjustments']:
        ar=client.post('/api/m8_cession/adjustments/%s/attribute'%adj['adj_id'],json={'destination':CURRENT_OFFSET})
        assert ar.status_code==200
    # 台账归属后重跑并覆盖保存同一批次，使归档状态反映已归属结论
    s=client.post('/api/runs',json={'sample':'dirty.csv'}).get_json()
    assert s['archive']['ready'] is True
    e=client.get('/api/archive/'+s['run_id']+'/export.csv');assert e.status_code==200 and '运行清单' in e.data.decode('utf-8-sig')
    assert '再保分出调整' in e.data.decode('utf-8-sig')

def test_export_blocked_when_cession_pending(client):
    client.post('/api/runs',json={'sample':'dirty.csv'})
    s=client.post('/api/runs',json={'sample':'dirty.csv'}).get_json()
    e=client.get('/api/archive/'+s['run_id']+'/export.csv')
    assert e.status_code==409 and e.get_json()['code']=='PENDING_ATTRIBUTION'
def test_idempotent_api(client):
    a=client.post('/api/runs',json={}).get_json();b=client.post('/api/runs',json={}).get_json()
    assert a['run_id']==b['run_id'] and len(client.get('/api/runs').get_json())==1
def test_bad_sample(client):
    r=client.post('/api/runs',json={'sample':'../x'});assert r.status_code==422 and r.get_json()['code']=='SAMPLE'
def test_missing_batch(client):
    assert client.get('/api/runs/absent').status_code==404
def test_bad_file(client):
    r=client.post('/api/runs',json={'csv':'wrong\n1\n'});assert r.status_code==422 and r.get_json()['code']=='HEADER'


def test_custom_source_is_visible_after_run(client):
    from app.workflow import load
    raw=load('clean.csv').decode('utf-8-sig');submitted=client.post('/api/runs',json={'csv':raw,'parameters':{}}).get_json()
    from app.config import MODULES
    page=client.get('/'+MODULES[0][0]);assert submitted['run_id'] in page.data.decode()

def test_reselect_existing_run_updates_visible_batch(client):
    a=client.post('/api/runs',json={'sample':'dirty.csv'}).get_json();b=client.post('/api/runs',json={'sample':'clean.csv'}).get_json();client.post('/api/runs',json={'sample':'dirty.csv'})
    assert client.get('/api/runs').get_json()[0]['id']==a['run_id'] and a['run_id']!=b['run_id']

def test_invalid_csv_type_rejected(client):
    assert client.post('/api/runs',json={'csv':123}).status_code==422

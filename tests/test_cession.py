import csv,io,pytest
from decimal import Decimal
from app.workflow import load,run
from app.errors import DomainError
from app.modules.m8_cession.reader import parse
from app.modules.m8_cession.rules import adjudicate,CURRENT_OFFSET,ORIGINAL_RESTATEMENT,PENDING
from app.modules.m8_cession import service,ledger,serializer

@pytest.fixture
def parsed():return parse(load('cession.csv'))

@pytest.fixture
def view(parsed):
    v=adjudicate(parsed,'2026-Q4');v['originals']=parsed['originals'];v['current_period']='2026-Q4';return v

def test_admitted_correction_starts_pending(view):
    # 起点：更正已采信，但再保去向未定
    assert len(view['adjustments'])==3
    assert all(a['status']=='待归属' and a['destination']==PENDING for a in view['adjustments'])
    assert view['summary']['pending_count']==3
    assert view['summary']['all_attributed'] is False

def test_closed_period_forbids_restatement(view):
    closed=[a for a in view['adjustments'] if a['period_closed']]
    assert len(closed)==2
    for a in closed:
        assert a['allowed_destinations']==[CURRENT_OFFSET]
        assert ORIGINAL_RESTATEMENT not in a['allowed_destinations']
        assert '已关闭' in a['rationale'] and '当期冲抵' in a['rationale']

def test_open_period_allows_both_destinations(view):
    opened=[a for a in view['adjustments'] if not a['period_closed']]
    assert len(opened)==1
    assert opened[0]['allowed_destinations']==[CURRENT_OFFSET,ORIGINAL_RESTATEMENT]

def test_ceded_amounts_use_share_and_decimal(view):
    p002=next(a for a in view['adjustments'] if a['policy_id']=='P002')
    # 保费 3650->4380，份额0.30：分出保费差额 (4380-3650)*0.30=219.00；赔款 (0->300)*0.30=90.00
    assert p002['premium_before']=='1095.00' and p002['premium_after']=='1314.00'
    assert p002['premium_delta']=='219.00'
    assert p002['claim_before']=='0.00' and p002['claim_after']=='90.00'
    assert p002['claim_delta']=='90.00' and p002['net_delta']=='129.00'

def test_net_conservation_between_two_methods(view):
    s=view['summary']
    # 当期冲抵全部入本期 = 开放账期重述额 + 已关账期（不可变）额
    assert s['net_conserved'] is True
    assert Decimal(s['current_offset_net'])==Decimal(s['restatement_net_open'])+Decimal(s['closed_period_net_immutable'])

def test_unadmitted_and_missing_reference_quarantined(view):
    codes={(q['id'],q['code']) for q in view['quarantine']}
    assert ('X0004','NOT_ADMITTED') in codes
    assert ('X0005','REFERENCE') in codes
    assert all(a['correction_id']!='X0004' for a in view['adjustments'])

def test_idempotent_rerun_creates_no_new_adjustment(view,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'c.db'))
    first=ledger.sync(view,'run-1');second=ledger.sync(view,'run-2')
    assert first['adjustments']==3 and second['adjustments']==0
    assert second['skipped_duplicates']==3
    assert len(ledger.snapshot()['adjustments'])==3

def test_original_record_never_overwritten(view,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'c.db'))
    ledger.sync(view,'run-1')
    tampered=dict(view);tampered['originals']=[dict(o,basis='被篡改的基线') for o in view['originals']]
    with pytest.raises(DomainError) as e:ledger.sync(tampered,'run-2')
    assert e.value.status==409 and e.value.code=='ORIGINAL_FROZEN'
    # 旧原记录仍可读取且内容不变
    assert ledger.snapshot()['originals'][0]['basis']=='原保单分出基线'

def test_attribute_closed_period_only_current_offset(view,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'c.db'))
    ledger.sync(view,'run-1')
    adj=next(a for a in view['adjustments'] if a['period_closed'])
    with pytest.raises(DomainError) as e:ledger.attribute(adj['adj_id'],ORIGINAL_RESTATEMENT,'rev')
    assert e.value.status==409 and e.value.code=='PERIOD_CLOSED'
    snap=ledger.attribute(adj['adj_id'],CURRENT_OFFSET,'rev')
    active=next(a for a in snap['adjustments'] if a['adj_id']==adj['adj_id'])
    assert active['destination']==CURRENT_OFFSET and active['status']=='已归属'

def test_switch_failure_keeps_old_version(view,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'c.db'))
    ledger.sync(view,'run-1')
    adj=next(a for a in view['adjustments'] if not a['period_closed'])
    ledger.attribute(adj['adj_id'],CURRENT_OFFSET,'v1')
    def boom():raise RuntimeError('切换中途失败')
    before=ledger.snapshot()
    with pytest.raises(RuntimeError):
        ledger.attribute(adj['adj_id'],ORIGINAL_RESTATEMENT,'v2',failure_hook=boom)
    # 切换失败：不晋升任何新版本，台账与失败前完全一致（旧版保留、可追溯）
    after=ledger.snapshot()
    assert after==before
    with ledger.connection() as db:
        rows=db.execute('SELECT version,active FROM cession_adjustments WHERE adj_id=? ORDER BY version',(adj['adj_id'],)).fetchall()
    # 成功的v1留下 v1(inactive)->v2(active)；失败的v3从未写入
    assert [(r['version'],r['active']) for r in rows]==[(1,0),(2,1)]
    active=next(a for a in after['adjustments'] if a['adj_id']==adj['adj_id'])
    assert active['destination']==CURRENT_OFFSET

def test_repeat_same_destination_is_noop(view,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'c.db'))
    ledger.sync(view,'run-1')
    adj=view['adjustments'][0]
    ledger.attribute(adj['adj_id'],CURRENT_OFFSET,'v1')
    with pytest.raises(DomainError) as e:ledger.attribute(adj['adj_id'],CURRENT_OFFSET,'v2')
    assert e.value.code=='SAME_DESTINATION'

def test_screen_and_download_share_single_source(view):
    projected=serializer.rows(view)
    csv_text=serializer.export_csv(view)
    header={label:key for key,label in serializer.COLUMNS}
    for row in projected:
        assert row['adj_id'] in csv_text and row[header['分出保费调整']] in csv_text
        assert row[header['赔款份额调整']] in csv_text and row[header['调整期间']]==view['current_period']
    reader=list(csv.reader(io.StringIO(csv_text.lstrip('﻿'))))
    assert reader[0][0]=='调整编号' and any(r and r[0]=='汇总' for r in reader)

def test_download_blocked_until_all_attributed(client,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'test.db'))
    r=client.get('/api/m8_cession/export.csv')
    assert r.status_code==409 and r.get_json()['code']=='PENDING_ATTRIBUTION'
    sync=client.post('/api/m8_cession/sync',json={})
    assert sync.status_code==200
    for adj in ledger.snapshot()['adjustments']:
        dest=CURRENT_OFFSET if adj['period_closed'] else ORIGINAL_RESTATEMENT
        rr=client.post('/api/m8_cession/adjustments/%s/attribute'%adj['adj_id'],json={'destination':dest})
        assert rr.status_code==200
    ok=client.get('/api/m8_cession/export.csv')
    assert ok.status_code==200 and ok.data.startswith('﻿'.encode())

def test_full_pipeline_carries_cession_and_archive_gate(raw,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'p.db'))
    state=run(raw,{})
    assert 'cession' in state and state['cession']['summary']['adjustment_count']==3
    # 起点台账无归属：归档就绪被再保待归属挡住
    assert state['archive']['cession_pending']==3
    assert state['archive']['ready'] is False

def test_archive_bundle_contains_cession_rows(raw,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'p.db'))
    state=run(raw,{})
    bundle=__import__('app.modules.m7_archive.export_out',fromlist=['bundle']).bundle(state)
    assert '再保分出调整' in bundle and '再保汇总' in bundle

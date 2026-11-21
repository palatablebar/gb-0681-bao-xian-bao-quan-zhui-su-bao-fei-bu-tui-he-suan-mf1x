from datetime import datetime,timezone
from flask import Blueprint,render_template,jsonify,request,Response
from app.config import TITLE,MODULES
from app.errors import DomainError
from app.modules.m8_cession import service,ledger,serializer

bp=Blueprint('m8_cession',__name__)
STAGE=8

@bp.get('/m8_cession')
def screen():
    view=service.build(_parameters())
    snap=ledger.snapshot()
    return render_template('m8_cession.html',title=TITLE,modules=MODULES,current=STAGE,
        data=_page_state(view),view=view,rows=serializer.rows(view),snap=snap,
        run={'decision':'再保台账','review_version':sum(v['version'] for v in snap['versions'])})

@bp.route('/api/m8_cession',methods=['GET','POST'])
def preview():
    view=service.build(_parameters())
    return jsonify({'adjustments':view['adjustments'],'summary':view['summary'],
        'quarantine':view['quarantine'],'rows':serializer.rows(view)})

@bp.post('/api/m8_cession/sync')
def sync():
    view=service.build(_parameters())
    created=ledger.sync(view,run_id='cession-sync')
    return jsonify({'created':created,'snapshot':ledger.snapshot()})

@bp.post('/api/m8_cession/adjustments/<adj_id>/attribute')
def attribute(adj_id):
    data=request.get_json(silent=True) or {}
    destination=data.get('destination')
    if not isinstance(destination,str):raise DomainError('DESTINATION','请提交归属去向')
    run_id=data.get('run_id','cession-review')
    snap=ledger.attribute(adj_id,destination,run_id)
    view=service.build(_parameters())
    return jsonify({'snapshot':snap,'summary':view['summary'],'rows':serializer.rows(view)})

@bp.get('/api/m8_cession/export.csv')
def download():
    view=service.build(_parameters())
    if not view['summary']['all_attributed']:
        raise DomainError('PENDING_ATTRIBUTION','存在待归属再保调整，结案下载需全部调整归属明确',409)
    return Response(serializer.export_csv(view),mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition':'attachment; filename=cession_adjustments.csv'})

def _parameters():
    data=request.get_json(silent=True) if request.method=='POST' else None
    data=data or {}
    if not isinstance(data,dict):raise DomainError('PAYLOAD','请求必须是对象')
    out={}
    if isinstance(data.get('parameters'),dict):out.update(data['parameters'])
    if data.get('cession_sample'):out['cession_sample']=data['cession_sample']
    if data.get('current_period'):out['current_period']=data['current_period']
    if 'cession_csv' in data:out['cession_csv']=data['cession_csv']
    return out

def _page_state(view):
    # base.html 期望的最小KPI结构
    return {'run_id':'cession-ledger',
        'manifest':{'generated_at':datetime.now(timezone.utc).isoformat(),'rule_version':'cession-2026.11','parameters':{}},
        'input_count':view['input_count'],'rows':[],'quarantine':view['quarantine'],
        'business':{'total':view['summary']['premium_delta'],'difference':view['summary']['net_delta']}}

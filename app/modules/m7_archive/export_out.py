import io,csv,json,hashlib
from app.modules.m8_cession.serializer import COLUMNS,rows as cession_rows

def bundle(state):
    out=io.StringIO(newline='');writer=csv.writer(out)
    writer.writerow(['记录类型','批次','来源行','业务ID','原因码','内容'])
    rid=state.get('run_id','preview')
    writer.writerow(['运行清单',rid,'','','',json.dumps(state.get('manifest',{}),ensure_ascii=False,sort_keys=True)])
    writer.writerow(['对账',rid,'','','',json.dumps(state.get('reconcile',{}),ensure_ascii=False,sort_keys=True)])
    for row in state.get('calculations',[]):writer.writerow(['计算',rid,row.get('line',''),row.get('id',''),row.get('code',''),json.dumps(row,ensure_ascii=False,sort_keys=True)])
    for row in state['quarantine']:writer.writerow(['隔离',rid,row['line'],row.get('id',''),row['code'],json.dumps(row.get('raw',{}),ensure_ascii=False,sort_keys=True)])
    cession=state.get('cession')
    if cession:
        writer.writerow(['再保汇总',rid,'','','',json.dumps(cession.get('summary',{}),ensure_ascii=False,sort_keys=True)])
        writer.writerow(['再保分出调整',rid,'','','','|'.join(label for _,label in COLUMNS)])
        for row in cession_rows(cession):
            writer.writerow(['再保分出调整',rid,'',row['adj_id'],'',json.dumps(row,ensure_ascii=False,sort_keys=True)])
        for q in cession.get('quarantine',[]):
            writer.writerow(['再保隔离',rid,q.get('line',''),q.get('id',''),q.get('code',''),json.dumps(q.get('raw',{}),ensure_ascii=False,sort_keys=True)])
    return '﻿'+out.getvalue()

def checksum(state):
    return hashlib.sha256(bundle(state).encode('utf-8')).hexdigest()

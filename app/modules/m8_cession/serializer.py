import csv,io,json

COLUMNS=[('adj_id','调整编号'),('ceded_id','原分出记录'),('correction_id','原更正依据'),
    ('policy_id','保单'),('original_period','原再保账期'),('current_period','调整期间'),
    ('period_closed','原账期是否关闭'),('share','分出份额'),
    ('premium_before','分出保费_更正前'),('premium_after','分出保费_更正后'),('premium_delta','分出保费调整'),
    ('claim_before','赔款份额_更正前'),('claim_after','赔款份额_更正后'),('claim_delta','赔款份额调整'),
    ('net_delta','净额调整'),('destination','归属去向'),('destination_label','归属说明'),
    ('status','状态'),('basis','更正依据'),('rationale','裁决理由')]

def rows(view):
    """复核界面与结案下载共用的行投影，保证看到同一分出保费、赔款份额、调整期间与更正依据。"""
    out=[]
    for a in view['adjustments']:
        row={key:a.get(key,'') for key,_ in COLUMNS}
        row['period_closed']='是' if a.get('period_closed') else '否'
        out.append(row)
    return out

def export_csv(view):
    buf=io.StringIO(newline='');writer=csv.writer(buf)
    writer.writerow([label for _,label in COLUMNS])
    for row in rows(view):writer.writerow([row[key] for key,_ in COLUMNS])
    writer.writerow([])
    writer.writerow(['汇总','调整笔数',view['summary']['adjustment_count'],'待归属',view['summary']['pending_count'],
        '分出保费调整合计',view['summary']['premium_delta'],'赔款份额调整合计',view['summary']['claim_delta'],
        '净额调整合计',view['summary']['net_delta'],'跨期净额守恒',str(view['summary']['net_conserved']).lower(),
        '全部已归属',str(view['summary']['all_attributed']).lower()])
    writer.writerow(['守恒','当期冲抵净额',view['summary']['current_offset_net'],
        '开放账期重述净额',view['summary']['restatement_net_open'],
        '已关账期净额(不可变)',view['summary']['closed_period_net_immutable']])
    writer.writerow(['隔离笔数',len(view['quarantine'])])
    for q in view['quarantine']:
        writer.writerow(['隔离',q.get('line',''),q.get('id',''),q.get('code',''),json.dumps(q.get('raw',{}),ensure_ascii=False,sort_keys=True)])
    return '﻿'+buf.getvalue()

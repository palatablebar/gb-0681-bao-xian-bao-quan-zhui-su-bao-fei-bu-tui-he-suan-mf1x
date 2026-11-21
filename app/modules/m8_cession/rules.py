import hashlib,json
from decimal import Decimal,ROUND_HALF_UP

CENT=Decimal('.01')
CURRENT_OFFSET='current_offset'
ORIGINAL_RESTATEMENT='original_restatement'
PENDING='pending'
DESTINATION_LABEL={CURRENT_OFFSET:'当期冲抵（追溯调整入本期末结账单）',
    ORIGINAL_RESTATEMENT:'原账期重述',PENDING:'待归属'}

def _q(value):
    return Decimal(str(value)).quantize(CENT,rounding=ROUND_HALF_UP)

def _adj_id(correction):
    raw=json.dumps({'ceded_id':correction['ceded_id'],'ref':correction['ref_ceded_id'],
        'policy_id':correction['policy_id'],'period':correction['period'],
        'premium_gross':str(correction['premium_gross']),'claim_gross':str(correction['claim_gross']),
        'share':str(correction['share']),'basis':correction['basis']},sort_keys=True,ensure_ascii=False)
    return 'ADJ-'+hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]

def _money(value):
    return str(_q(value))

def adjudicate(parsed,current_period,destinations=None):
    """唯一裁决入口：采信更正 -> 分出调整。destinations 为台账中已确认归属 {adj_id: destination}。"""
    destinations=destinations or {}
    originals={(o['policy_id'],o['period']):o for o in parsed['originals']}
    quarantine=[dict(q) for q in parsed['quarantine']]
    seen=set();adjustments=[]
    for c in parsed['corrections']:
        if not c['admitted']:
            quarantine.append({'line':c['line'],'id':c['ceded_id'],'code':'NOT_ADMITTED',
                'raw':{'basis':c['basis'],'note':'更正未采信，不形成再保分出调整'}});continue
        key=(c['policy_id'],c['period'])
        original=originals.get(key)
        if original is None or (c['ref_ceded_id'] and c['ref_ceded_id']!=original['ceded_id']):
            quarantine.append({'line':c['line'],'id':c['ceded_id'],'code':'REFERENCE',
                'raw':{'basis':c['basis'],'ref_ceded_id':c['ref_ceded_id'],'note':'找不到原分出记录，无法定位原账期'}});continue
        adj_id=_adj_id(c)
        if adj_id in seen:continue
        seen.add(adj_id)
        share=c['share']
        premium_before=_q(original['premium_gross']*share);premium_after=_q(c['premium_gross']*share)
        claim_before=_q(original['claim_gross']*share);claim_after=_q(c['claim_gross']*share)
        premium_delta=premium_after-premium_before;claim_delta=claim_after-claim_before
        closed=bool(original['period_closed'])
        allowed=[CURRENT_OFFSET] if closed else [CURRENT_OFFSET,ORIGINAL_RESTATEMENT]
        destination=destinations.get(adj_id,PENDING)
        if destination!=PENDING and destination not in allowed:destination=PENDING
        rationale=('原账期 %s 已关闭：重述会覆盖原分出记录并改写已关账净额，禁止入账；'
                   '唯一可入账结果为当期冲抵，原账不动、差额进入本期 %s 未结账单'
                   % (original['period'],current_period)) if closed else \
                  ('原账期 %s 尚未关闭，可在当期冲抵与原账期重述间归属，二者跨期净额合计恒等'
                   % original['period'])
        adjustments.append({'adj_id':adj_id,'ceded_id':original['ceded_id'],'correction_id':c['ceded_id'],
            'policy_id':c['policy_id'],'original_period':original['period'],'current_period':current_period,
            'period_closed':closed,'share':str(share),
            'premium_before':_money(premium_before),'premium_after':_money(premium_after),'premium_delta':_money(premium_delta),
            'claim_before':_money(claim_before),'claim_after':_money(claim_after),'claim_delta':_money(claim_delta),
            'net_delta':_money(premium_delta-claim_delta),
            'destination':destination,'status':'已归属' if destination!=PENDING else '待归属',
            'allowed_destinations':allowed,'destination_label':DESTINATION_LABEL[destination],
            'basis':c['basis'],'original_line':original['line'],'correction_line':c['line'],'rationale':rationale})
    summary=_summary(adjustments,current_period)
    return {'adjustments':adjustments,'quarantine':quarantine,'summary':summary,
        'input_count':parsed['input_count'],'blank_count':parsed['blank_count'],'encoding':parsed['encoding']}

def _summary(adjustments,current_period):
    premium=sum((Decimal(a['premium_delta']) for a in adjustments),Decimal(0))
    claim=sum((Decimal(a['claim_delta']) for a in adjustments),Decimal(0))
    net=premium-claim
    pending=[a for a in adjustments if a['destination']==PENDING]
    # 两种归属的跨期净额恒等：当期冲抵把全部差额计入本期；重述把差额留在原账期，合计相同。
    current_offset_total=net
    restatement_total=sum((Decimal(a['net_delta']) for a in adjustments if not a['period_closed']),Decimal(0))
    closed_total=sum((Decimal(a['net_delta']) for a in adjustments if a['period_closed']),Decimal(0))
    conserved=(current_offset_total==restatement_total+closed_total)
    return {'current_period':current_period,'adjustment_count':len(adjustments),'pending_count':len(pending),
        'premium_delta':_money(premium),'claim_delta':_money(claim),'net_delta':_money(net),
        'current_offset_net':_money(current_offset_total),
        'restatement_net_open':_money(restatement_total),'closed_period_net_immutable':_money(closed_total),
        'net_conserved':conserved,'all_attributed':len(pending)==0 and len(adjustments)>0,
        'unit':'CNY'}

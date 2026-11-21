import csv,io
from decimal import Decimal,InvalidOperation
from app.errors import DomainError
from app.modules.m1_ingest.decode import decode
from app.modules.m2_mapping.coerce import SENTINELS

REQUIRED=['kind','ceded_id','policy_id','period','period_closed','premium_gross','claim_gross','share','admitted','basis']
KINDS=('original','correction')
BOOLS={'true':True,'false':False}

def _decimal(value,line):
    text=str(value).strip()
    if text.upper() in SENTINELS:raise DomainError('MISSING','必填值缺失')
    try:
        result=Decimal(text)
        if not result.is_finite() or result<0:raise InvalidOperation
        return result
    except InvalidOperation:raise DomainError('NUMBER','数值无效')

def parse(raw):
    text,encoding=decode(raw)
    if not text:raise DomainError('EMPTY_FILE','文件为空')
    if not text.strip():raise DomainError('BLANK_FILE','文件仅含空行')
    reader=csv.reader(io.StringIO(text,newline=''))
    try:header=[s.strip().lstrip('﻿') for s in next(reader)]
    except (StopIteration,csv.Error):raise DomainError('HEADER','无法读取表头')
    if len(set(header))!=len(header) or not set(REQUIRED)<=set(header):raise DomainError('HEADER','表头缺失或重复')
    originals=[];corrections=[];quarantine=[];input_count=0;blank_count=0
    try:
        for row in reader:
            input_count+=1;line=reader.line_num
            if not row or not any(s.strip() for s in row):blank_count+=1;continue
            if len(row)!=len(header):
                quarantine.append({'line':line,'id':'','code':'WIDTH','raw':row});continue
            item=dict(zip(header,row))
            try:
                for field in REQUIRED:
                    if str(item.get(field,'')).strip().upper() in SENTINELS:raise DomainError('MISSING','必填值缺失')
                if item['kind'].strip() not in KINDS:raise DomainError('CONSTRAINT','记录类型无效')
                closed=BOOLS.get(item['period_closed'].strip().lower())
                if closed is None:raise DomainError('CONSTRAINT','账期关闭标识无效')
                admitted=BOOLS.get(item['admitted'].strip().lower())
                if admitted is None:raise DomainError('CONSTRAINT','采信标识无效')
                record={'kind':item['kind'].strip(),'line':line,'ceded_id':item['ceded_id'].strip(),'policy_id':item['policy_id'].strip(),
                    'period':item['period'].strip(),'period_closed':closed,
                    'premium_gross':_decimal(item['premium_gross'],line),'claim_gross':_decimal(item['claim_gross'],line),
                    'share':_decimal(item['share'],line),'admitted':admitted,'basis':item['basis'].strip(),
                    'ref_ceded_id':item.get('ref_ceded_id','').strip(),'note':item.get('note','').strip()}
                if not (Decimal(0)<=record['share']<=Decimal(1)):raise DomainError('RANGE','分出份额必须在0到1之间')
            except DomainError as error:
                quarantine.append({'line':line,'id':item.get('ceded_id',''),'code':error.code,'raw':dict(item)})
                continue
            (corrections if record['kind']=='correction' else originals).append(record)
    except csv.Error as exc:raise DomainError('CSV',str(exc))
    if input_count==0:raise DomainError('HEADER_ONLY','文件仅含表头')
    return {'originals':originals,'corrections':corrections,'quarantine':quarantine,
        'input_count':input_count,'blank_count':blank_count,'encoding':encoding}

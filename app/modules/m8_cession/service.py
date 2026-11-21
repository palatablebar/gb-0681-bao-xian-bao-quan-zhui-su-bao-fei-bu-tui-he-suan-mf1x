from pathlib import Path
from app.errors import DomainError
from app.modules.m8_cession.reader import parse
from app.modules.m8_cession.rules import adjudicate
from app.modules.m8_cession import ledger

DEFAULT_CURRENT_PERIOD='2026-Q4'

def load_sample(name):
    if name!='cession.csv':raise DomainError('SAMPLE','再保样例名称无效')
    return (Path(__file__).resolve().parents[3]/'sample_data'/name).read_bytes()

def build(parameters=None,read_ledger=True):
    parameters=parameters or {}
    name=parameters.get('cession_sample','cession.csv')
    content=parameters.get('cession_csv')
    raw=content.encode() if isinstance(content,str) else load_sample(name)
    current_period=parameters.get('current_period') or DEFAULT_CURRENT_PERIOD
    parsed=parse(raw)
    destinations=ledger.destinations() if read_ledger else {}
    view=adjudicate(parsed,current_period,destinations)
    view['originals']=parsed['originals']
    view['current_period']=current_period
    view['sample']=name
    return view

def execute(state):
    parameters=state.get('_parameters') or {}
    state['cession']=build(parameters)
    return state

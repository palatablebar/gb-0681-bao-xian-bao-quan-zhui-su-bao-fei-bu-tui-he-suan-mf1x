from app.modules.m7_archive.export_out import checksum

def execute(state):
    cession=state.get('cession',{})
    cession_ready=cession.get('summary',{}).get('all_attributed',True)
    state['archive']={'sha256':checksum(state),'evidence_count':len(state.get('calculations',[]))+len(state['quarantine']),
        'ready':state.get('reconcile',{}).get('balanced',False) and cession_ready,
        'cession_adjustments':cession.get('summary',{}).get('adjustment_count',0),
        'cession_pending':cession.get('summary',{}).get('pending_count',0)}
    return state

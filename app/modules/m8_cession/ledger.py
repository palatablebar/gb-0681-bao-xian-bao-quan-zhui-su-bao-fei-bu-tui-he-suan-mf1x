import json,sqlite3,os
from pathlib import Path
from app.errors import DomainError
from app.modules.m8_cession.rules import CURRENT_OFFSET,ORIGINAL_RESTATEMENT,PENDING

SCHEMA=(
    '''CREATE TABLE IF NOT EXISTS cession_originals(
        ceded_id TEXT PRIMARY KEY,body TEXT NOT NULL,created_run TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS cession_adjustments(
        adj_id TEXT NOT NULL,version INTEGER NOT NULL,body TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,created_run TEXT NOT NULL,
        PRIMARY KEY(adj_id,version))''',
    '''CREATE TABLE IF NOT EXISTS cession_audit(
        seq INTEGER PRIMARY KEY AUTOINCREMENT,adj_id TEXT NOT NULL,version INTEGER NOT NULL,
        action TEXT NOT NULL,destination TEXT NOT NULL,run_id TEXT NOT NULL,detail TEXT NOT NULL)''')

def connection():
    # isolation_level=None 进入自动提交模式，事务边界完全由显式 BEGIN/COMMIT/ROLLBACK 控制。
    path=Path(os.environ.get('DB_PATH','data/records.db'));path.parent.mkdir(parents=True,exist_ok=True)
    fresh=not path.exists()
    db=sqlite3.connect(path,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
    # 关键：PRAGMA journal_mode=WAL 是写操作，在事务中执行会隐式提交并使后续ROLLBACK失效。
    # 因此 WAL 只在数据库文件首次创建、尚无任何业务事务时设置一次；之后的连接只建表，绝不重放该PRAGMA。
    if fresh:db.execute('PRAGMA journal_mode=WAL')
    for ddl in SCHEMA:db.execute(ddl)
    return db

def _active_destinations(db):
    rows=db.execute('SELECT adj_id,body FROM cession_adjustments WHERE active=1').fetchall()
    return {r['adj_id']:json.loads(r['body']).get('destination',PENDING) for r in rows}

def sync(view,run_id):
    """只追加同步：原分出记录永不覆盖；同一更正重跑（adj_id相同）不新增调整。"""
    created={'originals':0,'adjustments':0,'skipped_duplicates':0,'refused_overwrites':0}
    db=connection()
    try:
        db.execute('BEGIN')
        for o in view['originals']:
            cur=db.execute('INSERT OR IGNORE INTO cession_originals(ceded_id,body,created_run) VALUES(?,?,?)',
                (o['ceded_id'],json.dumps(o,ensure_ascii=False,default=str),run_id))
            if cur.rowcount==1:created['originals']+=1
            else:
                old=json.loads(db.execute('SELECT body FROM cession_originals WHERE ceded_id=?',(o['ceded_id'],)).fetchone()['body'])
                if old!=json.loads(json.dumps(o,ensure_ascii=False,default=str)):
                    created['refused_overwrites']+=1
                    raise DomainError('ORIGINAL_FROZEN','原分出记录 %s 已封存，禁止覆盖；覆盖后已关账期对账无法解释'%o['ceded_id'],409)
        for a in view['adjustments']:
            cur=db.execute('INSERT OR IGNORE INTO cession_adjustments(adj_id,version,body,active,created_run) VALUES(?,1,?,1,?)',
                (a['adj_id'],json.dumps(a,ensure_ascii=False),run_id))
            if cur.rowcount==1:created['adjustments']+=1
            else:created['skipped_duplicates']+=1
        db.commit()
    except Exception:
        db.rollback();raise
    finally:
        db.close()
    return created

def attribute(adj_id,destination,run_id,failure_hook=None):
    if destination not in (CURRENT_OFFSET,ORIGINAL_RESTATEMENT):
        raise DomainError('DESTINATION','再保调整归属无效')
    db=connection()
    try:
        db.execute('BEGIN')
        row=db.execute('SELECT body,version FROM cession_adjustments WHERE adj_id=? AND active=1',(adj_id,)).fetchone()
        if row is None:raise DomainError('NOT_FOUND','再保调整不存在',404)
        body=json.loads(row['body']);old_destination=body.get('destination',PENDING);version=row['version']
        if destination not in body['allowed_destinations']:
            raise DomainError('PERIOD_CLOSED',
                '原账期 %s 已关闭，重述不可入账；唯一可入账归属为当期冲抵'%body['original_period'],409)
        if destination==old_destination:
            raise DomainError('SAME_DESTINATION','调整已归属该去向，重复提交不产生新版本',409)
        # 事务内先追加新版本，再翻转active；任何异常（含外部注入失败）整体回滚，旧版保持active。
        new_body=dict(body);new_body['destination']=destination
        new_body['destination_label']=('当期冲抵（追溯调整入本期末结账单）' if destination==CURRENT_OFFSET else '原账期重述')
        new_body['status']='已归属'
        db.execute('INSERT INTO cession_adjustments(adj_id,version,body,active,created_run) VALUES(?,?,?,0,?)',
            (adj_id,version+1,json.dumps(new_body,ensure_ascii=False),run_id))
        if failure_hook is not None:failure_hook()
        db.execute('UPDATE cession_adjustments SET active=0 WHERE adj_id=? AND version=?',(adj_id,version))
        db.execute('UPDATE cession_adjustments SET active=1 WHERE adj_id=? AND version=?',(adj_id,version+1))
        db.execute('INSERT INTO cession_audit(adj_id,version,action,destination,run_id,detail) VALUES(?,?,?,?,?,?)',
            (adj_id,version+1,'归属切换',destination,run_id,'旧版v%s=%s 保留可追溯'%(version,old_destination)))
        db.commit()
    except Exception:
        db.rollback();raise
    finally:
        db.close()
    return snapshot()

def snapshot():
    with connection() as db:
        rows=db.execute('SELECT adj_id,version,body FROM cession_adjustments WHERE active=1 ORDER BY adj_id').fetchall()
        audit=db.execute('SELECT adj_id,version,action,destination FROM cession_audit ORDER BY seq').fetchall()
        originals=db.execute('SELECT ceded_id,body FROM cession_originals ORDER BY ceded_id').fetchall()
    return {'adjustments':[json.loads(r['body']) for r in rows],
        'versions':[dict(r) for r in audit],
        'originals':[json.loads(r['body']) for r in originals]}

def destinations():
    with connection() as db:return _active_destinations(db)

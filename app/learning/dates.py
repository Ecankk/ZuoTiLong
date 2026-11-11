"""Known intervals and historical baselines; upload time is never attempt time."""
from datetime import date,datetime,timedelta
import calendar,re

def normalize(value=None,precision=None,reason=None):
    value=value or None
    inferred='unknown' if value is None else 'month' if re.fullmatch(r'\d{4}-\d{2}',value) else 'day'
    precision=precision or inferred
    if precision!=inferred:raise ValueError('作答日期与精度不一致')
    if value:
        if not re.fullmatch(r'\d{4}-\d{2}' if precision=='month' else r'\d{4}-\d{2}-\d{2}',value):raise ValueError('作答日期格式不正确')
        try:parsed=date.fromisoformat(value+'-01' if precision=='month' else value)
        except ValueError:raise ValueError('作答日期格式不正确') from None
        if parsed>date.today():raise ValueError('作答日期不能在未来')
        if reason is not None:raise ValueError('有日期时不能标记记不清')
    elif reason not in (None,'not_provided','forgotten'):raise ValueError('未知日期原因不正确')
    return dict(exam_date=value,exam_date_precision=precision,exam_date_unknown_reason=(reason or 'not_provided') if value is None else None)

def initialize(conn):
    columns={r[1] for r in conn.execute('PRAGMA table_info(papers)')}
    for name,definition in [('exam_date_precision','TEXT'),('exam_date_unknown_reason','TEXT'),('import_decision',"TEXT NOT NULL DEFAULT 'accepted'")]:
        if name not in columns:conn.execute('ALTER TABLE papers ADD COLUMN '+name+' '+definition)
    conn.execute("UPDATE papers SET exam_date_precision=CASE WHEN exam_date IS NULL OR exam_date='' THEN 'unknown' WHEN length(exam_date)=7 THEN 'month' ELSE 'day' END WHERE exam_date_precision IS NULL OR exam_date_precision=''")
    conn.execute("UPDATE papers SET exam_date_unknown_reason='not_provided' WHERE exam_date_precision='unknown' AND (exam_date_unknown_reason IS NULL OR exam_date_unknown_reason='')")
    conn.execute("UPDATE papers SET import_decision='accepted' WHERE import_decision IS NULL OR import_decision=''")
    conn.execute("UPDATE papers SET exam_date=NULL WHERE exam_date=''")

def descriptor(value=None,precision=None,reason=None):
    return dict(value=value or None,precision=precision or ('month' if value and len(value)==7 else 'day' if value else 'unknown'),unknown_reason=reason if value is None else None)

def interval(value,clock=None):
    if not value:return None
    try:
        if len(value)==7:
            y,m=map(int,value.split('-'));return date(y,m,1),min(date(y,m,calendar.monthrange(y,m)[1]),(clock.date() if isinstance(clock,datetime) else clock) or date.today())
        instant=datetime.fromisoformat(value.replace('Z','+00:00'))
        if instant.tzinfo is not None:instant=instant.astimezone(clock.tzinfo if isinstance(clock,datetime) else None)
        d=instant.date();return d,d
    except (ValueError,AttributeError,TypeError):return None

def groups(events):
    historical=[e for e in events if not interval(e.get('created_at'))]
    dated=sorted((e for e in events if interval(e.get('created_at'))),key=lambda e:(interval(e['created_at'])[0],e['id']))
    result=[historical] if historical else [];end=None
    for e in dated:
        a,b=interval(e['created_at'])
        if end is None or a>end:result.append([e]);end=b
        else:result[-1].append(e);end=max(end,b)
    return result

def mixed(events):
    kinds={e['kind'] for e in events}
    return bool(kinds & {'exam_error','probe_failure'} and kinds & {'exam_success','probe_success'})

def project(conn,events):
    papers={r['id']:dict(r) for r in conn.execute('SELECT * FROM papers')};result=[]
    for e in events:
        value=dict(e)
        if e['source']=='exam':
            p=papers[e['paper_id']];value['created_at']=p['exam_date'] or ''
            value['attempt_date']=descriptor(p['exam_date'],p.get('exam_date_precision'),p.get('exam_date_unknown_reason'))
        result.append(value)
    return result

def recent(value,clock,days=28):
    bounds=interval(value,clock)
    return bool(bounds and clock.date()-timedelta(days=days-1)<=bounds[0]<=bounds[1]<=clock.date())

def latest(facts):
    events=[dict(id=f['id'],created_at=f['occurred_at'] or '',fact=f) for f in facts]
    buckets=groups(events)
    if not buckets:return None
    last=buckets[-1]
    values={e['created_at'][:7] for e in last}
    if any(len(e['created_at'])==7 for e in last):return descriptor(next(iter(values)),'month')
    return descriptor(max(e['created_at'] for e in last)[:10] or None)

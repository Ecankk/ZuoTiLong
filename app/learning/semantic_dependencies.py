"""Append-only explanations for reusing evidence after a scoped review."""
import json,uuid
from app.learning.tasks import digest,encode
from app.learning.loop import stamp

def signature(question):
    return {'correctness':question.get('correctness'),'first_error':question.get('first_error'),
            'topics':sorted(set(question.get('knowledge',[]))|{e['skill_id'] for e in question.get('skill_events',[])})}

def reports_changed(inputs,current,baseline_id=None):
    if not inputs.get('reports') or not current:return set()
    old=json.loads(next((r for r in inputs['reports'] if r['id']==baseline_id),inputs['reports'][-1])['report_json'])
    before={str(q['number']):signature(q) for q in old['questions']}
    after={str(q['number']):signature(q) for q in current['questions']}
    return {n for n in set(before)|set(after) if before.get(n)!=after.get(n)}

def record(conn,kind,record_id,value):
    conn.execute('INSERT INTO record_versions VALUES(?,?,?,?,?,?)',
        ('version-'+uuid.uuid4().hex,kind,record_id,encode(value),'逐题语义依赖/v1',stamp()))

def after_review(conn,task,inputs,result,projection,old_sources):
    from app.knowledge.index import sources
    qid=inputs['question_review']['request']['question_id']
    before=signature(inputs['question_review']['question']);after=signature(result['question'])
    record(conn,'question_semantic_review',qid,{'schema':'mathlens.question-dependency/v1',
        'parent_report_id':inputs['question_review']['request']['report_id'],'report_id':projection['report_id'],
        'before':before,'after':after,'changed':before!=after})
    if before==after:
        old=next((s for s in old_sources if s['source_id']==qid),None)
        new=next((s for s in sources(conn,task['paper_id']) if s['source_id']==qid),None)
        if old and new:
            # Event IDs are execution identities; align unchanged semantic events.
            key=lambda e:(e['kind'],e.get('skill_id'))
            available={key(e):e['id'] for e in new['events']}
            events={e['id']:available[key(e)] for e in old['events'] if key(e) in available}
            record(conn,'knowledge_semantic_adoption',qid,{'source_id':qid,'from_revision':old['source_revision'],
                'to_revision':new['source_revision'],'signature':after,'events':events})

def adopt_mappings(conn,values):
    for row in conn.execute("SELECT payload FROM record_versions WHERE kind='knowledge_semantic_adoption' ORDER BY rowid"):
        adoption=json.loads(row[0]);key=(adoption['source_id'],adoption['from_revision'])
        if key not in values:continue
        import copy
        value=copy.deepcopy(values[key]);revision=adoption['to_revision']
        value['mapping']['source_revision']=revision
        for item in value['mapping'].get('event_topics',[]):item['event_id']=adoption['events'].get(item['event_id'],item['event_id'])
        if value['version']:value['version']['source_revision']=revision
        values.setdefault((adoption['source_id'],revision),value)

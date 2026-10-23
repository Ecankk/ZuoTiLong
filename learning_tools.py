"""Bounded, local learning operations used by the Codex MCP connection."""
import base64
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from agent_workspace import bank_catalog, workspace_context
from answer_images import image_records, image_path
from bank_access import require_access, review_cross, preferences
from learning_loop import apply_report, assess_attempt, revise_assessment, replace_probe, stamp

ACTIONS=('context','read_paper','catalog','read_bank','read_attempt','apply_report','assess','revise_assessment','replace_probe','review_cross','screen','read_skill','memory_read','memory_write')
SKILLS=('paper-diagnosis','bank-search','probe-design','learning-update')
SCHEMA={'type':'object','properties':{'action':{'type':'string','enum':list(ACTIONS)},'payload':{'type':'object'}},'required':['action','payload'],'additionalProperties':False}
DESCRIPTION='MathLens 本地学习接口。优先用此工具读取图片/技能/题库和写回评价，无需 Shell。action: context(payload可选paper_id); read_paper(paper_id,pages页码数组每次最多4页); catalog(topics数组、math_types数组、years数组、exclude_years数组、bank_id、offset、limit); read_bank(bank_id,role=question/analysis); read_attempt(attempt_id); apply_report(paper_id,report完整报告); assess(attempt_id,assessment:{correct:布尔或null,feedback,author,findings可选}); revise_assessment同assess加reason; replace_probe(probe_id,reason,changes); review_cross(bank_id,reason,distinct,other_id可选); screen({}); read_skill(name四个skills之一); memory_read/write(path相对memory路径,write需要text)。预留卷不检索。隐藏候选正文仅供内部阅读，不回显学生，先让学生在网页确认。'


def connection(data):
    conn=sqlite3.connect(data/'mathlens.db',timeout=15);conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON');return conn


def image_content(path,data):
    path=Path(path).resolve()
    if not path.is_relative_to(data.resolve()) or not path.is_file():raise ValueError('图片不在个人资料目录或不存在')
    from PIL import Image
    from io import BytesIO
    with Image.open(path) as img:
        output=BytesIO();img.convert('RGB').save(output,format='JPEG',quality=92)
    return {'type':'image','mimeType':'image/jpeg','data':base64.b64encode(output.getvalue()).decode()}


def execute(root,data,action,payload):
    if action not in ACTIONS or not isinstance(payload,dict):raise ValueError('学习操作不合法')
    images=[]
    with closing(connection(data)) as conn,conn:
        if action in ('apply_report','assess','revise_assessment','replace_probe','review_cross','memory_write'):
            with closing(sqlite3.connect(data/'agent-session.db')) as session:
                row=session.execute('SELECT payload FROM session WHERE id=1').fetchone()
            state=json.loads(row[0]) if row else {}
            if not state.get('active_request'):raise ValueError('没有正在处理的用户学习请求，拒绝写入')
            turn=next(t for t in state['turns'] if t['request_id']==state['active_request'])
            expected=turn.get('context',{}).get('paper_id')
            target=payload.get('paper_id')
            if payload.get('attempt_id'):
                r=conn.execute('SELECT p.paper_id FROM probe_attempts a JOIN diagnostic_probes p ON p.id=a.probe_id WHERE a.id=?',(payload['attempt_id'],)).fetchone();target=r[0] if r else None
            if payload.get('probe_id'):
                r=conn.execute('SELECT paper_id FROM diagnostic_probes WHERE id=?',(payload['probe_id'],)).fetchone();target=r[0] if r else None
            if expected and target and target!=expected:raise ValueError('写入目标不是当前讨论试卷')
        if action=='context':result=workspace_context(conn,data,payload.get('paper_id'))
        elif action=='read_paper':
            import pymupdf
            row=conn.execute('SELECT * FROM papers WHERE id=?',(payload['paper_id'],)).fetchone()
            if not row:raise ValueError('试卷不存在')
            path=(root/row['source_path']).resolve()
            if not path.is_relative_to(data):raise ValueError('试卷不在个人目录')
            pages=payload.get('pages',[1])
            if not isinstance(pages,list) or not 1<=len(pages)<=4 or any(type(p) is not int for p in pages):raise ValueError('每次读取 1–4 页')
            with pymupdf.open(path) as doc:
                if any(not 1<=p<=len(doc) for p in pages):raise ValueError('页码超界')
                for p in pages:
                    raw=doc[p-1].get_pixmap(matrix=pymupdf.Matrix(1.8,1.8),alpha=False).tobytes('png')
                    images.append({'type':'image','mimeType':'image/png','data':base64.b64encode(raw).decode()})
                result={'paper':dict(row),'page_count':len(doc),'pages':pages,'questions':[dict(q) for q in conn.execute('SELECT * FROM questions WHERE paper_id=?',(row['id'],))]}
        elif action=='catalog':result=bank_catalog(conn,data,**payload)
        elif action=='screen':
            path=data/'screen.json';result=json.loads(path.read_text(encoding='utf8')) if path.is_file() else {}
        elif action=='read_skill':
            name=payload['name'].removeprefix('mathlens-')
            if name not in SKILLS:raise ValueError('不存在该项目技能')
            result={'instructions':(root/'.agents/skills'/('mathlens-'+name)/'SKILL.md').read_text(encoding='utf8')}
        elif action=='read_bank':
            bid=payload['bank_id'];state=require_access(conn,bid,internal=True)
            role=payload.get('role','question')
            if role not in ('question','analysis','answer'):raise ValueError('资源类别不合法')
            row=conn.execute('SELECT * FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()
            if not row or not row[role+'_path']:raise ValueError('题库图片缺失')
            images.append(image_content(data/row[role+'_path'],data))
            visible=state['can_view'] if role=='question' else state['analysis_allowed']
            result={'bank_id':bid,'student_access':state,'internal_only':not visible,'policy':preferences(conn),
                    'instruction':('该检验题干可直接展示，不需要跨类别核准；解析另行由用户选择查看。' if visible and role=='question' else '当前资源仅内部阅读；仍隐藏的题干只给年份题号，未展示的解析不提前公布。' if not visible else '用户已选择查看解析，可结合实际作答讲解。')}
        elif action=='read_attempt':
            row=conn.execute('SELECT a.*,p.payload_json,p.paper_id,p.bank_id FROM probe_attempts a JOIN diagnostic_probes p ON p.id=a.probe_id WHERE a.id=?',(payload['attempt_id'],)).fetchone()
            if not row:raise ValueError('真实作答不存在')
            result=dict(row);ids=json.loads(result.pop('images_json'));result['image_ids']=ids;result['probe']=json.loads(result.pop('payload_json'))
            for record in image_records(conn,ids):images.append(image_content(image_path(record,data),data))
        elif action=='apply_report':result=apply_report(conn,payload['paper_id'],payload['report'],root)
        elif action=='assess':
            previous=conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(payload['attempt_id'],)).fetchone()
            result={'already_assessed':True,'assessment':json.loads(previous[0])} if previous and previous[0] else assess_attempt(conn,payload['attempt_id'],payload['assessment'])
        elif action=='revise_assessment':result=revise_assessment(conn,payload['attempt_id'],payload['assessment'],payload['reason'])
        elif action=='replace_probe':result=replace_probe(conn,payload['probe_id'],payload)
        elif action=='review_cross':result=review_cross(conn,**payload)
        else:
            path=(data/'memory'/payload['path']).resolve()
            if not path.is_relative_to((data/'memory').resolve()) or path.suffix not in ('.md','.json'):raise ValueError('记忆路径不合法')
            if action=='memory_write':
                text=payload.get('text','')
                if not isinstance(text,str) or len(text)>100000:raise ValueError('记忆过长')
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf8')
                result={'saved':str(path.relative_to(data))}
            else:result={'text':path.read_text(encoding='utf8') if path.is_file() else ''}
        conn.execute('CREATE TABLE IF NOT EXISTS tool_audit(id INTEGER PRIMARY KEY,action TEXT,record_id TEXT,created_at TEXT)')
        conn.execute('INSERT INTO tool_audit(action,record_id,created_at) VALUES(?,?,?)',(action,payload.get('attempt_id') or payload.get('bank_id') or payload.get('paper_id'),stamp()))
    return [{'type':'text','text':json.dumps(result,ensure_ascii=False)},*images]

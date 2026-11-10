"""Bounded, local learning operations used by the Codex MCP connection."""
from app.storage.paths import paper_path, relative_file, resolve_file, connection_data
import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from app.agent.workspace import bank_catalog, workspace_context
from app.storage.images import image_records, image_path
from app.bank.access import require_access, review_cross, preferences
from app.learning.loop import apply_report, assess_attempt, revise_assessment, replace_probe, stamp
from app.storage.boundaries import workspace_config, material_path, library_root, connect_workspace

ACTIONS=('context','task_context','preflight','deliver_result','read_paper','catalog','read_bank','read_attempt','apply_report','assess','revise_assessment','replace_probe','review_cross','screen','read_skill')
from app.agent.methods import SKILLS,skill_name,body as skill_body
SCHEMA={'type':'object','properties':{'action':{'type':'string','enum':list(ACTIONS)},'payload':{'type':'object'}},'required':['action','payload'],'additionalProperties':False,
    'allOf':[{'if':{'properties':{'action':{'enum':['deliver_result','preflight']}}},
              'then':{'properties':{'payload':{'type':'object','required':['result'],'properties':{'result':{'type':'object'}},'additionalProperties':False}}}},
             {'if':{'properties':{'action':{'const':'read_skill'}}},
              'then':{'properties':{'payload':{'type':'object','required':['name'],'properties':{'name':{'enum':list(SKILLS)+['mathlens-'+n for n in SKILLS]}},'additionalProperties':False}}}}]}
DESCRIPTION='图片读取首次调用就展示图片；exec模式返回含独立data:image行的字符串，按行将图片行传image()、其他行传text()，不要text(r)打印整体。做题龙单任务工具。方法、材料和回执已在初始包提供；材料齐全时直接deliver_result，校验失败按错误修正后再交，不例行preflight或context。deliver_result与preflight均传payload={result:完整任务封装}，与apply_report/assess一致。preflight仅供必要时调试，不保存。read_skill补读参数为{name:合法技能名}，技能名见材料包role_method。1.10选题仅补读候选题干。面向学生数学式用$...$或$$...$$包裹，隐藏材料仅内部阅读。'


def connection(data):
    return connect_workspace(workspace_config(data))


def image_content(path,data):
    path=Path(path).resolve()
    if not any(path.is_relative_to(p.resolve()) for p in (data,library_root(data))) or not path.is_file():raise ValueError('图片不在资料目录或不存在')
    from PIL import Image
    from io import BytesIO
    with Image.open(path) as img:
        output=BytesIO();img.convert('RGB').save(output,format='JPEG',quality=92)
    return {'type':'image','mimeType':'image/jpeg','data':base64.b64encode(output.getvalue()).decode()}


def execute(root,data,action,payload,*,lease=None):
    content=_execute(root,data,action,payload,lease=lease)
    if action=='read_bank' and content and content[0]['type']=='text':
        result=json.loads(content[0]['text'])
        with closing(connection(data)) as conn:
            from app.bank.errata import markers
            result['errata']=markers(conn,payload['bank_id'])
            if lease:
                task=conn.execute('SELECT input_json FROM learning_tasks WHERE id=?',(lease['task_id'],)).fetchone()
                inputs=json.loads(task[0])
                if 'free_practice' in inputs:result['errata']=inputs['free_practice']['snapshot'].get('errata',[])
                if 'profile_practice' in inputs:result['errata']=inputs['profile_practice']['snapshot'].get('errata',[])
            binding=result.get('material_binding')
            if binding:
                from app.bank.annotations import materials
                from app.learning.tasks import digest
                try:unchanged=digest(materials(conn,data,payload['bank_id']))==binding['material_revision']
                except ValueError:unchanged=False
                if not unchanged:result['errata']=[]
        content[0]={'type':'text','text':json.dumps(result,ensure_ascii=False)}
    return content


def _execute(root,data,action,payload,*,lease=None):
    if action not in ACTIONS or not isinstance(payload,dict):raise ValueError('学习操作不合法')
    if action in ('deliver_result','preflight') and (set(payload)!={'result'} or not isinstance(payload['result'],dict)):
        raise ValueError(action+'的payload必须为{result:完整任务封装}，封装包含schema_version、task_id、kind、paper_id、input_revision、author、result')
    if action=='read_skill':skill_name(payload)
    images=[]
    with closing(connection(data)) as conn,conn:
        if lease:
            row=conn.execute('SELECT kind FROM learning_tasks WHERE id=?',(lease.get('task_id'),)).fetchone()
            if row and row['kind'] in ('maintain_catalog','annotate_questions'):
                from app.storage.boundaries import enable_library_writes
                enable_library_writes(conn,workspace_config(data))
        task=None
        task_delivery=False
        if lease:
            from app.learning.tasks import check_lease
            task=check_lease(conn,lease,allow_completed=action in ('deliver_result','preflight') or action in ('apply_report','assess') and set(payload)=={'result'})
            task_inputs=json.loads(task['input_json'])
            if task_inputs.get('contract_version')=='1.12' and task['kind']=='grade_attempt' and action in ('read_bank','read_attempt','task_context'):
                from app.learning.profile_practice import supplement
                return supplement(conn,data,task,action,payload,image_content)
            if task_inputs.get('contract_version')=='1.11' and action in ('read_bank','read_attempt','task_context'):
                from app.learning.free_practice import supplement
                return supplement(conn,data,task,action,payload,image_content)
            if task['kind']=='prepare_practice' and task_inputs.get('contract_version') in ('1.10','1.12'):
                if action not in ('context','preflight','deliver_result','apply_report','read_bank','read_skill'):raise ValueError('选题只判断后端候选，不自行召回或读取候选外材料')
                if action=='read_bank' and (payload.get('bank_id') not in task_inputs['selection']['candidates'] or payload.get('role','question')!='question' or set(payload)-{'bank_id','role'}):
                    raise ValueError('选题补看仅限本次候选ID的题干图')
            task_delivery=action in ('apply_report','assess') and set(payload)=={'result'}
            if action in ('apply_report','assess','revise_assessment','replace_probe') and not task_delivery:
                raise ValueError('本任务须用apply_report/assess的payload.result提交完整任务契约，不能绕过保存回执')
            if task['kind']=='review_practice' and action not in ('context','task_context','read_skill','read_bank','apply_report','deliver_result','preflight'):
                raise ValueError('练习解答复核只读取固定题目与定义，不操作学生作答或重新选题')
            if task['kind'] in ('maintain_catalog','annotate_questions'):
                allowed={'context','task_context','read_skill','apply_report','deliver_result','preflight'}
                if task['kind']=='annotate_questions':allowed.add('read_bank')
                if action not in allowed:raise ValueError('通用资料任务只读取本批来源/题目/目录并交付，不操作个人学习记录')
        if action in ('apply_report','assess','revise_assessment','replace_probe','review_cross','memory_write') and not task_delivery:
            with closing(sqlite3.connect(data/'agent-session.db')) as session:
                row=session.execute('SELECT payload FROM session WHERE id=1').fetchone()
            state=json.loads(row[0]) if row else {}
            if not state.get('active_request'):raise ValueError('没有正在处理的用户学习请求，拒绝写入')
            turn=next(t for t in state['turns'] if t['request_id']==state['active_request'])
            if turn.get('task_id') and not lease:
                raise ValueError('当前是结构化学习任务，旧CLI或工具连接不能越过任务执行身份写入')
            expected=turn.get('context',{}).get('paper_id')
            target=payload.get('paper_id')
            if payload.get('attempt_id'):
                r=conn.execute('SELECT p.paper_id FROM probe_attempts a JOIN diagnostic_probes p ON p.id=a.probe_id WHERE a.id=?',(payload['attempt_id'],)).fetchone();target=r[0] if r else None
            if payload.get('probe_id'):
                r=conn.execute('SELECT paper_id FROM diagnostic_probes WHERE id=?',(payload['probe_id'],)).fetchone();target=r[0] if r else None
            if expected and target and target!=expected:raise ValueError('写入目标不是当前讨论试卷')
        if action=='preflight':
            from app.learning.tasks import preflight
            result=preflight(conn,root,data,payload['result'],lease)
        elif action=='deliver_result' or task_delivery:
            from app.learning.tasks import deliver
            result=deliver(conn,root,data,payload['result'],lease)
        elif action=='task_context':
            if not task:raise ValueError('当前不是结构化学习任务')
            from app.learning.tasks import task_package
            result=task_package(conn,task['id'])
            if task['kind'] in ('analyze_paper','review_question'):
                inputs=json.loads(task['input_json'])
                if inputs.get('contract_version')=='2.0':
                    from app.learning.paper_knowledge import prepared_context
                    from app.knowledge.mapping_versions import read_context
                    from app.learning.tasks import record_read,digest
                    scope=inputs['paper_knowledge']
                    if 'source_ids' in payload:raise ValueError('原卷分析读取原页与捕获参考，不使用知识整理source_ids')
                    if 'bank_ids' in payload:
                        if set(payload)!={'bank_ids'}:raise ValueError('通用参考与知识定义请分别读取')
                        result=prepared_context(conn,data,task,lease,payload['bank_ids'])
                    else:
                        content,ids=read_context({'knowledge_catalog':scope['catalog_nodes'],
                            'knowledge_catalog_revision':scope['catalog_revision']},payload)
                        if content is not None:result=content
                        known={n['id']:n for n in scope['catalog_nodes']}
                        for tid in ids:record_read(conn,lease,'paper_definition',tid,scope['catalog_revision'],digest(known[tid]))
            if task['kind']=='review_practice':
                inputs=json.loads(task['input_json']);scope=inputs['practice_review']
                from app.learning.tasks import record_read,digest
                if 'probe_ids' in payload:
                    ids=payload['probe_ids'];available={e['probe']['id']:e for e in scope['entries']}
                    if set(payload)!={'probe_ids'} or not isinstance(ids,list) or not 1<=len(ids)<=4 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids) or not set(ids).issubset(available):raise ValueError('每次读取本次1–4道不同练习的冻结解答')
                    result={'entries':[available[pid] for pid in ids],'request_note':scope['request']['note']}
                    for pid in ids:record_read(conn,lease,'practice_review',pid,'assignment',digest(available[pid]['probe']))
                else:
                    from app.knowledge.mapping_versions import read_context
                    content,ids=read_context({'knowledge_catalog':scope['catalog_nodes'],'knowledge_catalog_revision':scope['catalog_revision']},payload)
                    if content is not None:result=content
                    known={n['id']:n for n in scope['catalog_nodes']}
                    for tid in ids:record_read(conn,lease,'practice_review_definition',tid,scope['catalog_revision'],digest(known[tid]))
            if task['kind']=='grade_attempt':
                inputs=json.loads(task['input_json'])
                if inputs.get('contract_version')=='1.9':
                    from app.knowledge.mapping_versions import read_context
                    from app.learning.tasks import record_read,digest
                    scope=inputs['grading_knowledge']
                    if 'source_ids' in payload:raise ValueError('批改证据使用read_attempt，不使用知识整理来源接口')
                    content,ids=read_context({'knowledge_catalog':scope['catalog_nodes'],
                        'knowledge_catalog_revision':scope['catalog_revision']},payload)
                    if content is not None:result=content
                    known={n['id']:n for n in scope['catalog_nodes']}
                    for tid in ids:record_read(conn,lease,'grade_definition',tid,scope['catalog_revision'],digest(known[tid]))
            if task['kind']=='organize_knowledge':
                inputs=json.loads(task['input_json'])
                if inputs.get('contract_version')=='1.8':
                    from app.knowledge.mapping_versions import read_context
                    from app.learning.tasks import record_read,digest
                    content,ids=read_context(inputs,payload)
                    if content is not None:result=content
                    known={n['id']:n for n in inputs['knowledge_catalog']}
                    for tid in ids:
                        record_read(conn,lease,'knowledge_definition',tid,inputs['knowledge_catalog_revision'],digest(known[tid]))
            if task['kind']=='prepare_practice':
                inputs=json.loads(task['input_json'])
                if inputs.get('contract_version')=='1.9':
                    from app.knowledge.mapping_versions import read_context
                    from app.learning.tasks import record_read,digest
                    scope=inputs['practice_knowledge']
                    if 'source_ids' in payload:raise ValueError('选题原卷映射见任务包，不使用知识整理的source_ids读取')
                    content,ids=read_context({'knowledge_catalog':scope['catalog_nodes'],
                        'knowledge_catalog_revision':scope['catalog_revision']},payload)
                    if content is not None:result=content
                    known={n['id']:n for n in scope['catalog_nodes']}
                    for tid in ids:record_read(conn,lease,'practice_definition',tid,scope['catalog_revision'],digest(known[tid]))
            if task['kind'] in ('maintain_catalog','annotate_questions'):
                from app.knowledge import catalog as knowledge_catalog
                from app.learning.tasks import record_read
                inputs=json.loads(task['input_json'])
                if payload.get('reference_id') is not None:
                    if task['kind']!='maintain_catalog':raise ValueError('只有目录维护任务读取固定来源依据')
                    from app.knowledge.references import read as read_reference
                    result,paths=read_reference(data,inputs,payload)
                    images.extend(image_content(path,data) for path in paths)
                    record_read(conn,lease,'knowledge_reference',result['id'],inputs['task_scope']['source_version_id'],result['sha256'])
                elif payload.get('bank_ids') is not None:
                    if task['kind']!='annotate_questions':raise ValueError('只有题目标注任务读取固定题目分析上下文')
                    from app.bank.annotations import analysis_context
                    result=analysis_context(inputs,payload['bank_ids'])
                elif payload.get('source_ids') is not None:
                    if task['kind']!='maintain_catalog':raise ValueError('题目标注不读取目录维护来源')
                    ids=payload['source_ids'];available={e['source_id']:e for e in inputs['source_entries']}
                    if not isinstance(ids,list) or not 1<=len(ids)<=8 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids) or not set(ids).issubset(available):
                        raise ValueError('每次读取本批1–8个不同来源条目')
                    for sid in ids:record_read(conn,lease,'knowledge_source',sid,inputs['task_scope']['source_version_id'],available[sid]['content_sha256'])
                    from app.knowledge.maintenance import source_context
                    result=source_context(inputs,ids)
                elif payload.get('topic_ids') is not None:
                    ids=payload['topic_ids']
                    if not isinstance(ids,list) or not 1<=len(ids)<=30 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise ValueError('每次读取1–30个规范考点定义')
                    base=inputs.get('catalog_base') or knowledge_catalog.document(conn,inputs['catalog_revision'])['document']
                    nodes={n['id']:n for n in base['nodes']}
                    if not set(ids).issubset(nodes):
                        unknown=sorted(set(ids)-set(nodes))
                        raise ValueError('考点不属于本任务捕获目录：'+', '.join(unknown[:8])+'；请从目录查询复制完整ID，不能截短后缀；本批未登记任何定义阅读。')
                    for tid in ids:record_read(conn,lease,'knowledge_definition',tid,inputs['catalog_revision'] or 'outline',knowledge_catalog.digest(nodes[tid]))
                    result={'catalog_revision':inputs['catalog_revision'],'nodes':[nodes[tid] for tid in ids]}
                elif payload.get('knowledge_query') is not None:
                    query=payload['knowledge_query']
                    if not isinstance(query,dict) or not set(query).issubset({'query','parent_id','kinds','offset','limit'}):raise ValueError('目录查询字段不合法')
                    if inputs['catalog_revision']:
                        result=knowledge_catalog.search(conn,release_id=inputs['catalog_revision'],**query)
                    else:
                        key=knowledge_catalog.normalized(query.get('query',''))
                        nodes=inputs['catalog_base']['nodes']
                        result={'release_id':None,'items':[n for n in nodes if not key or key in knowledge_catalog.normalized(n['name'])]}
                    result['reading']='查询只作定位；复用/修改或标注前用topic_ids读取实际定义以登记依据。'
            if payload.get('knowledge_query') is not None and 'items' in result:
                from app.knowledge.catalog import navigation_result
                result=navigation_result(result)
            if task['kind']=='organize_knowledge' and payload.get('source_ids') is not None:
                from app.learning.tasks import record_read
                ids=payload['source_ids']
                if not isinstance(ids,list) or not 1<=len(ids)<=8 or len(set(ids))!=len(ids):raise ValueError('每次读取1–8个不同的来源ID')
                available={s['source_id']:s for s in json.loads(task['input_json'])['knowledge_sources']}
                if any(sid not in available for sid in ids):raise ValueError('知识证据不属于当前任务')
                for sid in ids:record_read(conn,lease,'knowledge',sid,'evidence',available[sid]['source_revision'])
                result={'sources':[available[sid] for sid in ids]}
                inputs=json.loads(task['input_json'])
                if inputs.get('contract_version')=='1.8':
                    from app.knowledge.source_hints import for_sources
                    hints=for_sources(conn,inputs,result['sources'])
                    if hints:result['source_topic_hints']=hints
        elif action=='context':
            if task and task['kind'] in ('organize_knowledge','grade_attempt','review_practice','maintain_catalog','annotate_questions','prepare_practice'):
                from app.learning.tasks import task_package
                result={'purpose':'本轮只执行当前阶段；原材料按需读取。','preferences':preferences(conn),'learning_task':task_package(conn,task['id'])}
            else:result=workspace_context(conn,data,payload.get('paper_id'))
            if task:
                from app.learning.tasks import task_package
                result['learning_task']=task_package(conn,task['id'])
                result['learning_task']['write_ticket']=lease
                if task['kind']=='summarize_paper':
                    result['task_packages']=[]
                    result['diagnosis_workflow']='当前为总结任务：用mathlens-learning-update，仅聚合已保存的reports/diagnoses/probes，不重新分析原卷。引用learning_task.allowed_source_refs；improvements只记录实际改善，建议放next_focus，无证据则为空。'
                elif task['kind']=='review_question':
                    result['task_packages']=[]
                    result['diagnosis_workflow']='当前只复核learning_task.question_review中的指定原题。read_paper传paper_id和question_id可取得原页、按旧区域自动放大的局部、可选说明及补图；其他题不重做。'
                elif task['kind']=='prepare_practice':
                    result['task_packages']=[]
                    result['diagnosis_workflow']='本轮只按已保存的原卷分析与考点关联筛选少量补强题，不重做切题或整卷诊断。保留原记录，先核已有练习与未覆盖环节；student_access仅控制学生网页展示，内部可读的隐藏题仍可按就绪/预留及历史规则选用。'
        elif action=='read_paper':
            import pymupdf
            import math
            row=conn.execute('SELECT * FROM papers WHERE id=?',(payload['paper_id'],)).fetchone()
            if not row:raise ValueError('试卷不存在')
            path=paper_path(data,row['source_path'],root)
            if not path.is_relative_to(data):raise ValueError('试卷不在个人目录')
            scope=None
            if payload.get('question_id'):
                if not task or task['kind']!='review_question' or task['paper_id']!=payload['paper_id']:
                    raise ValueError('本题材料只能由当前单题复核任务读取')
                scope=json.loads(task['input_json'])['question_review']
                if payload['question_id']!=scope['request']['question_id']:
                    raise ValueError('不能读取其他题的复核材料')
                if len({r['page'] for r in scope['question']['regions']}) > 4:
                    raise ValueError('本题超过4页，请分批读取原页；补图通过本题材料入口读取')
                payload={**payload,'pages':sorted({r['page'] for r in scope['question']['regions']}) or [1]}
            regions=payload.get('regions')
            if regions is not None and (not isinstance(regions,list) or not 1<=len(regions)<=4):
                raise ValueError('局部放大每次提供1–4个regions区域')
            if regions and any(not isinstance(r,dict) or set(r)!={'page','bbox'} for r in regions):
                raise ValueError('regions须为{page,bbox:[x0,y0,x1,y1]}，坐标使用原PDF点')
            pages=[r['page'] for r in regions] if regions else payload.get('pages',[1])
            if not isinstance(pages,list) or not 1<=len(pages)<=4 or any(type(p) is not int for p in pages):raise ValueError('每次读取 1–4 页')
            with pymupdf.open(path) as doc:
                if any(not 1<=p<=len(doc) for p in pages):raise ValueError('页码超界')
                if regions:
                    for region in regions:
                        bbox=region['bbox'];page=doc[region['page']-1]
                        if (not isinstance(bbox,list) or len(bbox)!=4
                            or any(type(x) not in (int,float) or not math.isfinite(x) for x in bbox)
                            or not 0<=bbox[0]<bbox[2]<=page.rect.width
                            or not 0<=bbox[1]<bbox[3]<=page.rect.height):
                            raise ValueError('局部区域坐标无效或超出原PDF页面')
                for i,p in enumerate(pages):
                    scale=3 if regions else 1.8
                    raw=doc[p-1].get_pixmap(matrix=pymupdf.Matrix(scale,scale),
                        clip=pymupdf.Rect(regions[i]['bbox']) if regions else None,alpha=False).tobytes('png')
                    images.append({'type':'image','mimeType':'image/png','data':base64.b64encode(raw).decode()})
                result={'paper':dict(row),'page_count':len(doc),'pages':pages,
                        'page_dimensions':[{'page':p,'width':doc[p-1].rect.width,'height':doc[p-1].rect.height,
                                            'unit':'PDF points','image_scale':3 if regions else 1.8} for p in pages],
                        'read_scope':'regions' if regions else 'full_pages','regions':regions or [],
                        'coordinate_instruction':'regions.bbox使用原PDF点坐标[x0,y0,x1,y1]，不是返回图片的像素；每页尺寸见page_dimensions。',
                        'questions':[dict(q) for q in conn.execute('SELECT * FROM questions WHERE paper_id=?',(row['id'],))]}
                from app.learning.analysis_materials import expectations
                result.update(expectations(conn,dict(row)))
                if not task or task['kind'] in ('analyze_paper', 'review_question'):
                    from app.bank.paper_candidates import locate
                    result['bank_locator_candidates'] = locate(conn, dict(row),
                        selected_number=scope['question']['number'] if scope else None)
                if scope:
                    for region in scope['question']['regions'][:4]:
                        page=doc[region['page']-1]
                        rect=(pymupdf.Rect(region['bbox'])+(-18,-18,18,18)) & page.rect
                        raw=page.get_pixmap(matrix=pymupdf.Matrix(3,3),clip=rect,alpha=False).tobytes('png')
                        images.append({'type':'image','mimeType':'image/png','data':base64.b64encode(raw).decode()})
                    for record in image_records(conn,scope['request']['image_ids']):
                        images.append(image_content(image_path(record,data),data))
                    result['question_review']=scope
                    result['image_order']='先是完整原页，再是本题原区域（四边适度扩展）的局部图，最后按image_ids顺序附加补图。补图可能是重拍原作答、事后批改或外部解析；不能将事后材料当成独立练习成功。'
            if task:
                from app.learning.tasks import record_read,resource_digest
                sha=resource_digest(path,data)
                for i,page in enumerate(pages):
                    record_read(conn,lease,'paper_region' if regions else 'paper',row['id'],
                        json.dumps(regions[i],sort_keys=True) if regions else str(page),sha)
                if scope:
                    from app.learning.tasks import digest
                    record_read(conn,lease,'question_review',scope['request']['question_id'],'materials',digest(scope))
        elif action=='catalog':
            query=dict(payload)
            if set(query)-{'topics','bank_id','offset','limit','math_types','years','exclude_years','topic_ids','stages','methods','include_history'}:
                raise ValueError('catalog可用参数：题源导航topics/bank_id/years/exclude_years/offset/limit；原子召回topic_ids/stages/methods/include_history/offset/limit。查询规范定义请用task_context({knowledge_query:{query:"名称"}})，不支持catalog.query。')
            old_scope=query.pop('math_types',None)
            if 'topic_ids' in query:
                if not set(query).issubset({'topic_ids','stages','methods','offset','limit','include_history'}):
                    raise ValueError('原子检索字段不合法；题源粗分类导航与原子检索请分别调用')
                from app.bank.retrieval import recall
                inputs=json.loads(task['input_json']) if task else {}
                strict=bool(task and task['kind']=='prepare_practice' and inputs.get('contract_version')=='1.9')
                if strict:
                    scope=inputs['practice_knowledge'];known={n['id'] for n in scope['catalog_nodes']}
                    if not set(query['topic_ids']).issubset(known):raise ValueError('查询考点不属于本任务捕获目录')
                    result=recall(conn,data,internal=True,allowed_annotations=set(scope['annotation_manifest']),**query)
                    from app.learning.practice_knowledge import recalled
                    for item in result['items']+result['existing_exercises']:
                        if item.get('probe_id') in scope['legacy_review']:
                            item.update(can_reuse=False,review_reason=scope['legacy_review'][item['probe_id']])
                            continue
                        item['material_binding']=recalled(conn,data,task,lease,item['id'],item['annotation_id'])
                else:result=recall(conn,data,internal=True,**query)
            else:
                result=bank_catalog(conn,data,**query)
                result['retrieval_mode']='source_navigation'
                result['prepared_search']='用topic_ids指定已发布原子/子树，可选stages/methods；只返回就绪题及原练习引用。'
            result['retrieval_scope']='统一题池；数学类别仅为出处/适用元数据和学生展示保护，不限制学习选题。'
            result['agent_access_policy']={'student_mask_limits_agent':False,
                'student_can_view_is_display_only':True,'new_selection_requires_ready':True,
                'reserved_questions_excluded':True}
            if old_scope:
                result['scope_note']='已忽略旧math_types筛选参数；请按考点、目标环节和实际内容选择。'
        elif action=='screen':
            path=data/'screen.json';result=json.loads(path.read_text(encoding='utf8')) if path.is_file() else {}
        elif action=='read_skill':
            name=skill_name(payload)
            result={'instructions':skill_body(root,name)}
            if task:
                from app.learning.tasks import task_package
                result['learning_task_contract']={'task_id':task['id'],'kind':task['kind'],
                  'input_revision':task['input_revision'],'result_schema':task_package(conn,task['id'])['result_schema'],
                  'write_action':'assess' if task['kind']=='grade_attempt' else 'apply_report',
                  'payload':'{result: 完整任务结果JSON}；本任务契约优先于旧报告/probes说明'}
                from app.agent.bridge import FORMULAS
                result['learning_task_contract']['student_math_format']=FORMULAS
            if name in ('paper-diagnosis','knowledge-index','bank-search','probe-design','learning-update'):
                from app.knowledge.index import compact_catalog, reference_policy
                result['knowledge_catalog']=compact_catalog(conn)
                if task and task['kind'] in ('analyze_paper','review_question'):
                    inputs=json.loads(task['input_json'])
                    if inputs.get('contract_version')=='2.0':
                        result['knowledge_catalog']=[{k:n[k] for k in ('id','parent_id','name','aliases')}
                            for n in inputs['paper_knowledge']['catalog_nodes']]
                if task and task['kind']=='organize_knowledge':
                    result['knowledge_catalog']=task_package(conn,task['id'])['knowledge_catalog']
                if task and task['kind']=='prepare_practice':
                    inputs=json.loads(task['input_json'])
                    if inputs.get('contract_version')=='1.9':
                        result['knowledge_catalog']=[{k:n[k] for k in ('id','parent_id','name','aliases')}
                            for n in inputs['practice_knowledge']['catalog_nodes']]
                if task and task['kind']=='grade_attempt':
                    inputs=json.loads(task['input_json'])
                    if inputs.get('contract_version')=='1.9':
                        result['knowledge_catalog']=[{k:n[k] for k in ('id','parent_id','name','aliases')}
                            for n in inputs['grading_knowledge']['catalog_nodes']]
                result['catalog_policy']=reference_policy()
            elif name in ('catalog-maintenance','question-topics'):
                from app.knowledge.catalog import active_id
                result['catalog_revision']=active_id(conn)
                result['catalog_policy']={'mode':'scoped_catalog_maintenance' if name=='catalog-maintenance' else 'reference_existing_only',
                    'node_changes_allowed':bool(task and task['kind']=='maintain_catalog'),
                    'reading':'用task_context的knowledge_query定位，再用topic_ids读取定义；不灌入整套目录。'}
            if name=='paper-diagnosis':
                workflow=(root/'docs/agent-workflow.md').read_text(encoding='utf8')
                # The versioned schema above is the machine contract. This is
                # human guidance; rewording/reordering a documentation heading
                # must not break the learning tool or hide its actual schema.
                result['report_contract']=workflow
            elif name=='bank-search':
                for key,relative in (('source_catalog','docs/question-sources.md'),('source_interface','docs/bank-source-interface.md')):
                    raw=(root/relative).read_bytes()
                    result[key]={'path':relative,'sha256':hashlib.sha256(raw).hexdigest(),'text':raw.decode('utf8')}
        elif action=='read_bank':
            bid=payload['bank_id']
            from app.agent.practice_materials import read as read_practice_materials
            fixed=read_practice_materials(conn,data,task,lease,payload,image_content)
            if fixed is not None:return fixed
            from app.learning.paper_knowledge import read as read_paper_reference
            fixed=read_paper_reference(conn,data,task,lease,payload,image_content)
            if fixed is not None:return fixed
            if task and task['kind']=='annotate_questions':
                from app.bank import annotations
                from app.bank.access import access
                from app.learning.tasks import record_read
                inputs=json.loads(task['input_json'])
                available={q['bank_id']:q for q in inputs['bank_questions']}
                if bid not in available:raise ValueError('题目不在本批通用标注范围')
                role=payload.get('role','question')
                roles=list(available[bid]['materials']) if role=='all' else [role]
                if any(r not in available[bid]['materials'] for r in roles):raise ValueError('本题没有该材料角色')
                if annotations.materials(conn,data,bid)!=available[bid]['materials']:raise ValueError('题目材料已变化，请按当前版本重建任务')
                resources=[]
                for resource_role in roles:
                    material=available[bid]['materials'][resource_role]
                    image_index=None
                    if material['path']:
                        images.append(image_content(material_path(data,material['path']),data));image_index=len(images)
                    record_read(conn,lease,'bank_preparation',bid,resource_role,material['sha256'])
                    resources.append({'role':resource_role,'text':material['text'],'sha256':material['sha256'],'image_index':image_index})
                result={'bank_id':bid,'resources':resources,
                        'student_access':access(conn,bid),'internal_only':True,
                        'instruction':'仅供通用题目准备，不向学生展示，不记录学生看题/看解析或作答成功。'}
                conn.execute('CREATE TABLE IF NOT EXISTS tool_audit(id INTEGER PRIMARY KEY,action TEXT,record_id TEXT,created_at TEXT)')
                conn.execute('INSERT INTO tool_audit(action,record_id,created_at) VALUES(?,?,?)',(action,bid,stamp()))
                return [{'type':'text','text':json.dumps(result,ensure_ascii=False)},*images]
            state=require_access(conn,bid,internal=True)
            role=payload.get('role','question')
            if role not in ('question','analysis','answer'):raise ValueError('资源类别不合法')
            row=conn.execute('SELECT * FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()
            if not row:raise ValueError('题库资源缺失')
            from app.bank.annotations import materials
            standard=json.loads(row['metadata_json']).get('schema')=='mathlens.bank-record/v1'
            material=materials(conn,data,bid).get(role) if standard or not row[role+'_path'] else {'text':''}
            if not material:raise ValueError('题库资源缺失')
            if row[role+'_path']:
                images.append(image_content(material_path(data,row[role+'_path']),data))
            if task:
                from app.learning.tasks import record_read,resource_digest
                sha=resource_digest(material_path(data,row[role+'_path']),data) if row[role+'_path'] else material['sha256']
                record_read(conn,lease,'bank',bid,role,sha)
            visible=state['can_view'] if role=='question' else state['analysis_allowed']
            result={'bank_id':bid,'student_access':state,'internal_only':not visible,'policy':preferences(conn),
                    'resource_sha256':{key:hashlib.sha256(material_path(data,row[key+'_path']).read_bytes()).hexdigest()
                                       for key in ('question','analysis','answer') if row[key+'_path'] and material_path(data,row[key+'_path']).is_file()},
                    'instruction':('该检验题干可直接展示，不需要跨类别核准；解析另行由用户选择查看。' if visible and role=='question' else '当前资源仅内部阅读；仍隐藏的题干只给年份题号，未展示的解析不提前公布。' if not visible else '用户已选择查看解析，可结合实际作答讲解。')}
            if material['text']:
                result['text']=material['text']
                result['resource_sha256'][role]=material['sha256'] if not row[role+'_path'] else result['resource_sha256'].get(role)
            if task and task['kind']=='prepare_practice':
                inputs=json.loads(task['input_json'])
                if inputs.get('contract_version')=='1.9':
                    from app.bank import annotations
                    from app.learning.practice_knowledge import material_binding
                    annotation=annotations.current(conn,data,bid)
                    if (annotation and annotation['analysis']['status']=='ready'
                            and annotation['id'] in inputs['practice_knowledge']['annotation_manifest']):
                        result['prepared_question']=annotations.prepared_summary(annotation)
                        result['prepared_question']['material_binding']=material_binding(conn,data,bid,annotation)
                        result['prepared_question']['internal_only']=True
                        result['prepared_question'].setdefault('reading','已核通用解法仅供内部选题判断，不提前展示答案/解析。仍核对本次实际题图/参考与训练目的；其他来源的参考材料不因同题关系自动获得相同审核结论，冲突须保留。')
        elif action=='read_attempt':
            row=conn.execute('SELECT a.*,p.payload_json,p.paper_id,p.bank_id FROM probe_attempts a JOIN diagnostic_probes p ON p.id=a.probe_id WHERE a.id=?',(payload['attempt_id'],)).fetchone()
            if not row:raise ValueError('真实作答不存在')
            result=dict(row);ids=json.loads(result.pop('images_json'));result['image_ids']=ids;result['probe']=json.loads(result.pop('payload_json'))
            result['image_roles']=json.loads(result.pop('image_roles_json','{}'))
            result['material_instruction']='按image_ids顺序阅读；image_roles区分own_work自己的作答、external_solution外部解析、marking事后批改。外部资料不是学生独立解答；只有外部图时correct须为null，请求自己的作答。以probe.prompt为本次回答范围，未布置的小问不算漏做；再read_bank独立核验，不能只匹配expected。'
            if task:
                inputs=json.loads(task['input_json'])
                if task['kind']=='grade_attempt' and inputs.get('contract_version')=='1.9':
                    result['material_binding']=inputs['grading_knowledge']['binding']
                    result['material_instruction']+=' read_bank自动读取本次固定题目版本，可用role=all；task_context(topic_ids)读取本任务捕获考点定义。'
            for record in image_records(conn,ids):images.append(image_content(image_path(record,data),data))
            if task:
                from app.learning.tasks import record_read,digest
                attempt=conn.execute('SELECT * FROM probe_attempts WHERE id=?',(payload['attempt_id'],)).fetchone()
                record_read(conn,lease,'attempt',payload['attempt_id'],'response',digest(dict(attempt)))
        elif action=='apply_report':result=apply_report(conn,payload['paper_id'],payload['report'],root)
        elif action=='assess':
            previous=conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(payload['attempt_id'],)).fetchone()
            result={'already_assessed':True,'assessment':json.loads(previous[0])} if previous and previous[0] else assess_attempt(conn,payload['attempt_id'],payload['assessment'])
        elif action=='revise_assessment':result=revise_assessment(conn,payload['attempt_id'],payload['assessment'],payload['reason'])
        elif action=='replace_probe':result=replace_probe(conn,payload['probe_id'],payload)
        elif action=='review_cross':result=review_cross(conn,**payload)
        else:raise ValueError('学习操作尚未实现')
        conn.execute('CREATE TABLE IF NOT EXISTS tool_audit(id INTEGER PRIMARY KEY,action TEXT,record_id TEXT,created_at TEXT)')
        conn.execute('INSERT INTO tool_audit(action,record_id,created_at) VALUES(?,?,?)',(action,payload.get('attempt_id') or payload.get('bank_id') or payload.get('paper_id'),stamp()))
    return [{'type':'text','text':json.dumps(result,ensure_ascii=False)},*images]

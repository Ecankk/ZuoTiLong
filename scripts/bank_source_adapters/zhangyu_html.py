"""S03 pinned book parts, converted without import or corrections."""
import hashlib,json
from pathlib import Path
from app.bank.source_records import SCHEMA,resource,digest
from scripts.extra_bank_adapters.zhangyu_html import adapt_zhangyu,KNOWN_REVISION

REVISION=KNOWN_REVISION
TYPES={'选择':'choice','填空':'fill','解答':'proof'}
PARTS={'strengthening':(range(32,68),683),'comprehensive':(range(68,72),88),'basic':(range(1,32),536)}

def convert(item):
    source=item['source'];identity=item['identity'];content=item['content']
    kind=item['upstream']['question_type'].removesuffix('题')
    if kind not in TYPES:raise ValueError('Unknown S03 question type: '+str(kind))
    if content['illustrations']:raise ValueError('Pinned S03 subset unexpectedly contains images')
    book=dict(title=identity['book_title_claimed'],edition=identity['edition_label_claimed'],part=identity['part'],
        chapter=identity['chapter_title'],number=None,locator=source['source_uid'])
    if identity['part']=='强化篇':book['number']=str(source['source_question_number'])
    if identity['part']=='综合篇':
        book['number']=str(source['source_question_number'])
        book['locator']=book['chapter']+' / 第 '+book['number']+' 题'
    # chapter-local numbers are source locators, not verified printed book IDs.
    return dict(schema=SCHEMA,source_id='S03',revision=REVISION,source_uid=source['source_uid'],
        locator=dict(path=source['source_file'],pointer='#q'+str(source['source_question_number']),source_sha256=source['source_file_sha256']),
        exam_year=None,math_type=None,number=None,math_types=[1],question_type=TYPES[kind],max_score=None,
        stem=resource(content['stem']),answer=resource(content['answer'] or ''),analysis=resource(content['explanation']),
        options=[dict(label=o['key'],content=resource(o['value'])) for o in content['options']],
        original=dict(source_text=book['title']+' / '+book['part']+' / '+book['chapter']+' / '+book['locator'],
            record=item,sha256=digest(item)),book=book,tags=['测试卷',book['chapter']] if identity['part']=='综合篇' else [identity['subject'],identity['chapter_title'],identity['part']])

def adapt(root,*,year=None,math_type=None,parts=None):
    if year is not None or math_type is not None:raise ValueError('S03 book chapters are not exam identities')
    parts=['strengthening'] if parts is None else parts
    if not parts or len(set(parts))!=len(parts) or any(p not in PARTS for p in parts):raise ValueError('parts must select distinct strengthening/comprehensive/basic')
    chapters=sorted(c for p in parts for c in PARTS[p][0])
    root=Path(root)
    expected=json.loads(Path(__file__).with_suffix('.hashes.json').read_text(encoding='utf-8'))
    for name in ['index.html']+[f'chapters/chapter-{c:02d}.html' for c in chapters]:
        sha=expected[name]
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:raise ValueError('Pinned S03 file SHA256 mismatch: '+name)
    result=[convert(item) for item in adapt_zhangyu(root,revision=REVISION,chapters=tuple(chapters))]
    if len(result)!=sum(PARTS[p][1] for p in parts):raise ValueError('Pinned S03 selected parts question count mismatch')
    return result

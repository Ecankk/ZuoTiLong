"""S03 pinned strengthening chapters, converted without import or corrections."""
import hashlib,json
from pathlib import Path
from app.bank.source_records import SCHEMA,resource,digest
from scripts.extra_bank_adapters.zhangyu_html import adapt_zhangyu,KNOWN_REVISION

REVISION=KNOWN_REVISION
TYPES={'选择':'choice','填空':'fill','解答':'proof'}

def convert(item):
    source=item['source'];identity=item['identity'];content=item['content']
    kind=item['upstream']['question_type'].removesuffix('题')
    if kind not in TYPES:raise ValueError('Unknown S03 question type: '+str(kind))
    if content['illustrations']:raise ValueError('Pinned S03 subset unexpectedly contains images')
    book=dict(title=identity['book_title_claimed'],edition=identity['edition_label_claimed'],part=identity['part'],
        chapter=identity['chapter_title'],number=None,locator=source['source_uid'])
    # chapter-local numbers are source locators, not verified printed book IDs.
    return dict(schema=SCHEMA,source_id='S03',revision=REVISION,source_uid=source['source_uid'],
        locator=dict(path=source['source_file'],pointer='#q'+str(source['source_question_number']),source_sha256=source['source_file_sha256']),
        exam_year=None,math_type=None,number=None,question_type=TYPES[kind],max_score=None,
        stem=resource(content['stem']),answer=resource(content['answer'] or ''),analysis=resource(content['explanation']),
        options=[dict(label=o['key'],content=resource(o['value'])) for o in content['options']],
        original=dict(source_text=book['title']+' / '+book['part']+' / '+book['chapter']+' / '+book['locator'],
            record=item,sha256=digest(item)),book=book,tags=[identity['subject'],identity['chapter_title'],'强化篇'])

def adapt(root,*,year=None,math_type=None):
    if year is not None or math_type is not None:raise ValueError('S03 adapter only accepts strengthening chapters 32–67; these are not exam identities')
    root=Path(root)
    expected=json.loads(Path(__file__).with_suffix('.hashes.json').read_text(encoding='utf-8'))
    for name,sha in expected.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:raise ValueError('Pinned S03 file SHA256 mismatch: '+name)
    result=[convert(item) for item in adapt_zhangyu(root,revision=REVISION)]
    if len(result)!=683:raise ValueError('Pinned S03 strengthening subset must contain 683 records')
    return result

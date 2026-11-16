"""Convert the fixed cxy snapshot, with no corrections or database access."""
import json
import mimetypes
from pathlib import Path
import re

from app.bank.source_records import SCHEMA, resource, digest, sha256, asset_path

REVISION = '7e79423253454dfb32246b6a84c7d6fd6efaa5b8'
FILE_SHA256 = '64139ef2b530205bbcbe589e4b2621d0be29f10919c23d740d06203d8d4bda7d'
FILE = 'library/bundled-library.json'
TYPE = {'一': 1, '二': 2, '三': 3}
SOURCE = re.compile(r'^(?P<year>(?:19|20)\d{2})年?[·\s]*(?:数学|数)(?P<types>[一二三]+)(?P<suffix>.*)$')
ASSET = re.compile(r'asset://[0-9a-f]{64}')
S02_PARTS = {
    'lilin-880': ('李林880题', '0.88k'),
    'wuzhongxiang-yanxuan': ('武忠祥严选', '严选'),
    'cxy-1k': ('1k题源', '1k'),
}


def claims(question, year, math_type):
    """Read only explicit original-exam source labels; book editions are not exams."""
    numbers = set()
    matched = False
    for field in ('source', 'original_source', 'source_details'):
        label = question.get(field) or ''
        if not isinstance(label, str):
            raise ValueError('Expected source label text')
        m = SOURCE.fullmatch(label.strip())
        if not m or int(m['year']) != year or math_type not in [TYPE[t] for t in m['types']]:
            continue
        matched = True
        if len(m['types']) > 1:
            numbers.update(int(n) for t, n in re.findall(r'([一二三])\s*(\d{1,3})', m['suffix']) if TYPE[t] == math_type)
        else:
            n = re.search(r'第\s*(\d{1,3})\s*题|[（(]\s*(\d{1,3})\s*[）)]', m['suffix'])
            if n:
                numbers.add(int(n[1] or n[2]))
    if len(numbers) > 1:
        raise ValueError('Conflicting source question numbers: ' + str(question['id']))
    return matched, next(iter(numbers), None)


def convert(snapshot, *, revision, source_sha256, year=2026, math_type=1):
    questions = snapshot['questions']
    if not isinstance(questions, list) or not isinstance(snapshot.get('assetMap', {}), dict):
        raise ValueError('Unexpected cxy questions/assetMap structure')
    result = []
    for index, question in enumerate(questions):
        matched, number = claims(question, year, math_type)
        if not matched:
            continue
        document = question.get('document') or {}
        def material(text):
            if not isinstance(text, str):
                raise ValueError('Expected cxy material text: ' + str(question['id']))
            images = []
            for ref in dict.fromkeys(ASSET.findall(text)):
                mapped = snapshot.get('assetMap', {}).get(ref)
                if not mapped:
                    raise ValueError('Unresolved cxy asset: ' + ref)
                path = 'public/' + mapped.lstrip('/')
                media = mimetypes.guess_type(path)[0]
                images.append(dict(path=path, sha256=ref.split('://')[1], media_type=media))
            return resource(text, images)
        answer = question.get('answer') or document.get('answer') or {}
        options = question.get('options') or document.get('options') or []
        kind = question.get('question_type') or document.get('question_type')
        result.append(dict(schema=SCHEMA, source_id='S02', revision=revision, source_uid=str(question['id']),
            locator=dict(path=FILE, pointer='/questions/' + str(index), source_sha256=source_sha256),
            exam_year=year, math_type=math_type, number=number,
            question_type={'single_choice': 'choice', 'fill': 'fill', 'essay': 'proof'}.get(kind), max_score=None,
            stem=material(question.get('stem') or document.get('stem_md') or ''),
            options=[dict(label=o['label'], content=material(o['content_md'])) for o in options],
            answer=material(question.get('correct_answer') or answer.get('reference_answer_md') or ''),
            analysis=material(question.get('answer_explanation') or document.get('explanation_md') or ''),
            original=dict(source_text='\n'.join(dict.fromkeys(question.get(k) or '' for k in
                ('source', 'original_source', 'source_details'))), record=question, sha256=digest(question)),
            tags=list(dict.fromkeys(question.get('source_tags') or []))))
    return result


def _book_number(label):
    match=re.search(r'第\s*(\d+)\s*题',label or '')
    return match.group(1) if match else None


def _book_chapter(label, question):
    for value in (label, question.get('category_name'), question.get('category_full_path')):
        match=re.search(r'第\s*([0-9一二三四五六七八九十百]+)\s*章',value or '')
        if match:return match.group(1)
    return None


def _convert_s02_parts(snapshot, *, revision, source_sha256, selected):
    result=[]
    for index,question in enumerate(snapshot['questions']):
        tags=list(dict.fromkeys(question.get('source_tags') or []))
        matched=[name for name,(_,token) in S02_PARTS.items() if name in selected and any(token in str(tag) for tag in tags)]
        if not matched:continue
        part=matched[0]; part_name=S02_PARTS[part][0]
        document=question.get('document') or {}
        def material(value):
            text_value=value if isinstance(value,str) else ''
            images=[]
            for ref in dict.fromkeys(ASSET.findall(text_value)):
                mapped=snapshot.get('assetMap',{}).get(ref)
                if not mapped:raise ValueError('Unresolved cxy asset: '+ref)
                path='public/'+mapped.lstrip('/');media=mimetypes.guess_type(path)[0]
                images.append(dict(path=path,sha256=ref.split('://')[1],media_type=media))
            return resource(text_value,images)
        options=question.get('options') or document.get('options') or []
        kind=question.get('question_type') or document.get('question_type')
        normalized={'single_choice':'choice','choice':'choice','fill':'fill','essay':'proof','subjective':'proof','proof':'proof'}.get(kind)
        label='；'.join(str(value) for value in (question.get('source'),question.get('original_source'),question.get('source_details')) if value)
        answer_obj=question.get('answer') if isinstance(question.get('answer'),dict) else {}
        document_answer=document.get('answer') if isinstance(document.get('answer'),dict) else {}
        answer_value='' if normalized=='proof' else (question.get('correct_answer') or answer_obj.get('reference_answer_md') or document_answer.get('reference_answer_md') or '')
        chapter=_book_chapter(label,question);number=_book_number(label)
        book=dict(title=part_name,edition=None,part=part_name,chapter=chapter,number=number,
                  locator=(label or ('/questions/'+str(index))))
        result.append(dict(schema=SCHEMA,source_id='S02',revision=revision,source_uid=str(question['id']),
            locator=dict(path=FILE,pointer='/questions/'+str(index),source_sha256=source_sha256),
            exam_year=None,math_type=None,number=None,question_type=normalized,max_score=None,
            stem=material(question.get('stem') or document.get('stem_md') or ''),
            options=[dict(label=o['label'],content=material(o.get('content_md',''))) for o in options],
            answer=material(answer_value),analysis=material(question.get('answer_explanation') or document.get('explanation_md') or ''),
            original=dict(source_text=label,record=question,sha256=digest(question)),
            tags=list(dict.fromkeys(tags+[part_name])),book=book))
    return result


def adapt(root, *, year=None, math_type=None, parts=None):
    year=2026 if year is None else year
    math_type=1 if math_type is None else math_type
    raw = (Path(root) / FILE).read_bytes()
    sha = sha256(raw)
    if sha != FILE_SHA256:
        raise ValueError('cxy input differs from the pinned revision; review and version the adapter first')
    if parts:
        selected=set(parts)
        unknown=selected-set(S02_PARTS)
        if unknown:raise ValueError('Unknown cxy part: '+','.join(sorted(unknown)))
        batch=_convert_s02_parts(json.loads(raw),revision=REVISION,source_sha256=sha,selected=selected)
        for record in batch:
            for part in [record[r] for r in ('stem','answer','analysis')]+[o['content'] for o in record['options']]:
                for image in part['images']:
                    if sha256(asset_path(root,image['path']).read_bytes())!=image['sha256']:
                        raise ValueError('cxy asset checksum mismatch: '+image['path'])
        return batch
    if (year,math_type)!=(2026,1):
        raise ValueError('This pinned adapter release covers only 2026 mathematics I; review source claims before expanding it')
    batch = convert(json.loads(raw), revision=REVISION, source_sha256=sha, year=year, math_type=math_type)
    # Validate every emitted image without importing or copying it.
    for record in batch:
        for part in [record[r] for r in ('stem', 'answer', 'analysis')] + [o['content'] for o in record['options']]:
            for image in part['images']:
                if sha256(asset_path(root, image['path']).read_bytes()) != image['sha256']:
                    raise ValueError('cxy asset checksum mismatch: ' + image['path'])
    return batch

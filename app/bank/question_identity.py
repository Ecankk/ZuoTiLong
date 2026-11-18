"""Exact full-question signatures, not mathematical similarity or reference trust."""
import re
import unicodedata
from app.bank import source_records as r

SCHEMA='question_identity_signature/v1'
COMPLETENESS_FIELDS=('stem','options','images','target')


def text(value):
    return unicodedata.normalize('NFC',(value or '').replace('\r\n','\n'))


def signature(record,asset_root,*,completeness=None,hashes=None):
    """Completeness is explicit external evidence, never inferred from a hash.

    Callers may share a hash cache only inside their single read-only preview.
    Payload contains question content: do not include it in public reports.
    """
    hashes={} if hashes is None else hashes;issues=[]
    def images(items):
        result=[]
        for image in items:
            try:
                path=r.asset_path(asset_root,image['path'])
                if path not in hashes:hashes[path]=r.sha256(path.read_bytes())
                actual=hashes[path]
                if actual!=image['sha256']:raise ValueError('hash_mismatch')
                result.append(actual)
            except (ValueError,OSError):
                issues.append('image_missing_unsafe_or_hash_mismatch')
                result.append('unverified:'+image['sha256'])
        return result
    def part(value):
        if r.sha256(value['text'].encode('utf8'))!=value['sha256']:issues.append('text_hash_mismatch')
        if re.search(r'!\[|<img\b|asset://|data:image|\\includegraphics',value['text'],re.I) and not value['images']:
            issues.append('unresolved_image_reference')
        return dict(text=text(value['text']),images=images(value['images']))
    stem=part(record['stem']);options=[];labels=set()
    for option in sorted(record['options'],key=lambda o:o['label']):
        label=text(option['label'])
        if label in labels:issues.append('duplicate_option_label')
        labels.add(label);options.append(dict(label=label,content=part(option['content'])))
        if not option['content']['text'].strip() and not option['content']['images']:issues.append('empty_option')
    sup=record.get('supplemental_figures',{})
    # Materialized stems already contain the supplements in their composite.
    figures=images([e['image'] for e in sorted(sup.get('entries',[]),key=lambda e:e['figure_id'])
                    if e['role']=='stem']) if 'stem' not in sup.get('materialized_roles',[]) else []
    kind=record.get('question_type')
    if kind not in ('choice','fill','proof'):issues.append('unknown_question_type')
    if not stem['text'].strip() and not stem['images']:issues.append('missing_stem')
    if re.search(r'待补充题干|题干见原图|题面见原图|暂缺题干',stem['text']) and not stem['images']:issues.append('placeholder_stem')
    if re.search(r'!\[|<img\b|asset://|data:image|\\includegraphics',stem['text'],re.I) and not stem['images']:
        issues.append('unresolved_image_reference')
    if kind=='choice' and len(options)<2:issues.append('incomplete_options')
    proof=completeness or {}
    if not all(proof.get(k) is True for k in COMPLETENESS_FIELDS) or not str(proof.get('evidence','')).strip():
        issues.append('completeness_unproven')
    payload=dict(schema=SCHEMA,question_type=kind,stem=stem,options=options,supplemental_stem_images=figures)
    return dict(schema=SCHEMA,sha256=r.digest(payload),payload=payload,
                automatic_eligible=not issues,issues=sorted(set(issues)))

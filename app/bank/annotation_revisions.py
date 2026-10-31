"""Frozen, explicitly bounded revisions of existing local question analyses.

The normal annotation contract is unchanged. A revision supplies a complete
result, while fields outside its grant must remain equal to the captured base.
"""
import copy
from app.knowledge import catalog

EDITABLE_FIELDS = ('reference_reasoning', 'answer_check.note', 'limitations',
                   'bindings', 'methods', 'checkpoints', 'fingerprint')


def normalize(value, bank_ids):
    if not isinstance(value, dict) or set(value) != {'expected_annotations', 'allowed_fields'}:
        raise ValueError('窄修订须明确expected_annotations和allowed_fields')
    expected, fields = value['expected_annotations'], value['allowed_fields']
    if (not isinstance(expected, dict) or set(expected) != set(bank_ids)
            or any(not isinstance(nid, str) or not catalog.ID.fullmatch(nid) for nid in expected.values())):
        raise ValueError('窄修订须逐题指定有效的原标注ID，范围须与bank_ids一致')
    if (not isinstance(fields, list) or not 1 <= len(fields) <= len(EDITABLE_FIELDS)
            or any(not isinstance(field, str) for field in fields)
            or len(set(fields)) != len(fields) or not set(fields).issubset(EDITABLE_FIELDS)):
        raise ValueError('窄修订须指定不同的可修改字段，不能修改材料身份或直接升级就绪状态')
    return {'expected_annotations': {bid: expected[bid] for bid in sorted(expected)},
            'allowed_fields': sorted(fields)}


def capture_bases(conn, data, bank_ids, request):
    from app.bank.annotations import current
    bases = {}
    for bid in bank_ids:
        value = current(conn, data, bid)
        if (not value or value.get('cache_provenance') or value['analysis']['status'] != 'ready'
                or value['id'] != request['expected_annotations'][bid]):
            raise ValueError('原标注已变化、失效或不是本机完整就绪标注，须重新核对修订基线：' + bid)
        bases[bid] = value
    return bases


def frozen_base(previous, source, request):
    value = copy.deepcopy(previous['analysis'])
    # A confirmed alias may use a different source image/title identity. The
    # verified mathematics is retained, but the delivery identity is this task's.
    value.update(bank_id=source['bank_id'], content_revision=source['content_revision'],
                 material_revision=source['material_revision'])
    return {'annotation_id': previous['id'], 'source_bank_id': previous['source_bank_id'],
            'allowed_fields': request['allowed_fields'], 'analysis': value}


def existing_binding_ids(source):
    base = source.get('revision_base')
    return {item['topic_id'] for item in base['analysis']['bindings']} if base else set()


def introduces_binding_collision(source, ids, resolved):
    """Keep frozen historical merges without admitting a new duplicate tag."""
    preserved = existing_binding_ids(source)
    groups = {}
    for tid in ids:
        groups.setdefault(resolved[tid], set()).add(tid)
    return any(len(group) > 1 and not group.issubset(preserved) for group in groups.values())


def validate(source, incoming):
    saved = source.get('revision_base')
    if not saved:
        return
    baseline, fields = saved['analysis'], set(saved['allowed_fields'])
    # A newly discovered uncertainty must be able to remove this question from
    # the ready pool. It cannot be turned into an unauthorized promotion.
    downgrade = incoming['status'] in ('needs_review', 'needs_catalog')
    if downgrade:
        if not incoming['limitations']:
            raise ValueError('窄修订发现实质问题时须明确具体限制，不能无依据降为待核')
        if incoming['status'] == 'needs_catalog' and not incoming['unmatched_topics']:
            raise ValueError('目录缺口须具体说明未匹配的必要考点')
        fields.update({'status', 'answer_check.note', 'answer_check.status', 'limitations', 'unmatched_topics'})
    changed = []
    for key, value in baseline.items():
        if key == 'answer_check':
            changed.extend('answer_check.' + sub for sub, old in value.items()
                           if 'answer_check.' + sub not in fields and incoming[key][sub] != old)
        elif key not in fields and incoming[key] != value:
            changed.append(key)
    if changed:
        raise ValueError('窄修订不能改变未授权字段：' + ', '.join(sorted(changed)) + '；请从revision_base复制原字段')

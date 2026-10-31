"""Fixed delivery shapes for the two shared-knowledge task kinds."""


def shape(kind):
    from app.learning.contracts import obj, array, string, ID, SHA, TEXTS, IDS, STAGE, FINGERPRINT
    if kind == 'maintain_catalog':
        node = obj({'id': ID, 'parent_id': {'anyOf': [ID, {'type': 'null'}]},
                    'name': string(nonempty=True, limit=160), 'kind': {'enum': ['subject','chapter','topic','atom']},
                    'definition': string(nonempty=True), 'conditions': TEXTS, 'boundaries': TEXTS,
                    'aliases': TEXTS, 'math_types': array({'enum': [1,2,3]}, unique=True, maximum=3),
                    'source_refs': array(obj({'source_version_id': ID, 'source_id': ID}), maximum=100),
                    'review_note': string(nonempty=True, limit=4000)})
        return obj({'summary': string(nonempty=True), 'node_changes': array(node, maximum=120),
                    'redirects': array(obj({'old_id': ID,'target_id': ID,'reason': string(nonempty=True)}), maximum=100),
                    'source_resolutions': array(obj({'source_id': ID,
                        'disposition': {'enum': ['mapped','method','navigation','excluded','pending']},
                        'node_ids': IDS, 'reason': string(nonempty=True)}), minimum=1, maximum=40),
                    'limitations': TEXTS})
    if kind == 'annotate_questions':
        binding = obj({'topic_id': ID, 'role': {'enum': ['primary','supporting','prerequisite']},
                       'evidence': string(nonempty=True), 'stages': array(STAGE, minimum=1, unique=True, maximum=6)})
        question = obj({'bank_id': ID, 'content_revision': SHA, 'material_revision': SHA,
                        'status': {'enum': ['ready','needs_catalog','needs_review']},
                        'reference_reasoning': string(nonempty=True),
                        'answer_check': obj({'status': {'enum': ['consistent','conflict','missing']}, 'note': string(nonempty=True)}),
                        'bindings': array(binding, maximum=30), 'methods': TEXTS,
                        'checkpoints': array(obj({'stage': STAGE,'description': string(nonempty=True)}), maximum=30),
                        'fingerprint': FINGERPRINT, 'unmatched_topics': TEXTS, 'limitations': TEXTS})
        return obj({'summary': string(nonempty=True), 'questions': array(question, minimum=1, maximum=8), 'limitations': TEXTS})
    raise ValueError('未知通用知识任务')

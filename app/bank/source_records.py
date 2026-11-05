"""Versioned interchange records and metadata-only, auditable corrections."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from jsonschema import Draft202012Validator

SCHEMA = 'mathlens.bank-record/v1'
OVERRIDES_SCHEMA = 'mathlens.bank-overrides/v1'
SHA = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
TEXT = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


RESOURCE = obj({'text': {'type': 'string'}, 'sha256': SHA, 'images': {'type': 'array', 'items': obj({
    'path': TEXT, 'sha256': SHA, 'media_type': {'enum': ['image/png', 'image/jpeg', 'image/webp']}})}})
IDENTITY = {'exam_year': {'type': ['integer', 'null'], 'minimum': 1900, 'maximum': 9999},
            'math_type': {'enum': [1, 2, 3, None]},
            'number': {'type': ['integer', 'null'], 'minimum': 1, 'maximum': 999}}
METADATA = {**IDENTITY, 'question_type': {'enum': ['choice', 'fill', 'proof', None]},
            'max_score': {'type': ['number', 'null'], 'minimum': 0}}
RECORD_SCHEMA = obj({'schema': {'const': SCHEMA}, 'source_id': {'type': 'string', 'pattern': '^S[0-9]{2,}$'},
    'revision': TEXT, 'source_uid': TEXT,
    'locator': obj({'path': TEXT, 'pointer': TEXT, 'source_sha256': SHA}), **METADATA,
    'stem': RESOURCE, 'answer': RESOURCE, 'analysis': RESOURCE,
    'options': {'type': 'array', 'items': obj({'label': TEXT, 'content': RESOURCE})},
    'original': obj({'source_text': {'type': 'string'}, 'record': {'type': 'object'}, 'sha256': SHA}),
    'tags': {'type': 'array', 'items': TEXT, 'uniqueItems': True}})
# Optional additive provenance for books; absent is equivalent to unknown.
RECORD_SCHEMA['properties']['book']=obj({k:{'type':['string','null']} for k in ('title','edition','part','chapter','number','locator')})
RECORD_SCHEMA['properties']['math_types']={'type':'array','uniqueItems':True,'items':{'type':'integer','enum':[1,2,3]}}
RECORD_SCHEMA['properties']['errata']={'type':'array','items':obj({'match':obj({'source_uid':TEXT}),'role':{'type':'string','pattern':'^(stem|answer|analysis|option:.+)$'},'find':{'type':'string','minLength':1},'replace':{'type':'string'},'reason':TEXT,'evidence':TEXT})}
OVERRIDE_FIELDS = {**METADATA, 'exclude': {'type': 'boolean'}}
OVERRIDE_SCHEMA = obj({'schema': {'const': OVERRIDES_SCHEMA}, 'source_id': RECORD_SCHEMA['properties']['source_id'],
    'revision': TEXT, 'entries': {'type': 'array', 'items': obj({
        'match': {'oneOf': [obj({'source_uid': TEXT}), obj({k: {**v, 'type': 'integer'} if 'type' in v else
            {'enum': [1, 2, 3]} for k, v in IDENTITY.items()})]},
        'set': {'type': 'object', 'properties': OVERRIDE_FIELDS, 'minProperties': 1, 'additionalProperties': False},
        'reason': TEXT, 'evidence': TEXT})}})


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def resource(text='', images=None):
    return {'text': text, 'sha256': sha256(text.encode('utf8')), 'images': images or []}


def bank_id(record):
    return 'src-' + record['source_id'].lower() + '-' + sha256(record['source_uid'].encode('utf8'))[:24]


def asset_path(root, path):
    relative = PurePosixPath(path)
    if (relative.is_absolute() or PureWindowsPath(path).drive or '\\' in path or
            any(p in ('..', '.') for p in path.split('/'))):
        raise ValueError('Invalid relative asset path: ' + path)
    actual = (Path(root) / path).resolve()
    if not actual.is_relative_to(Path(root).resolve()):
        raise ValueError('Asset escapes source root: ' + path)
    return actual


def validate(record, asset_root):
    canonical(record)  # Also reject non-finite JSON numbers in otherwise free original records.
    Draft202012Validator(RECORD_SCHEMA).validate(record)
    if isinstance(record['math_type'], bool):
        raise ValueError('math_type must be an integer')
    for part in [record[k] for k in ('stem', 'answer', 'analysis')] + [o['content'] for o in record['options']]:
        if sha256(part['text'].encode('utf8')) != part['sha256']:
            raise ValueError('Text SHA256 mismatch: ' + record['source_uid'])
        for image in part['images']:
            if sha256(asset_path(asset_root, image['path']).read_bytes()) != image['sha256']:
                raise ValueError('Image SHA256 mismatch: ' + image['path'])
    if digest(record['original']['record']) != record['original']['sha256']:
        raise ValueError('Original record SHA256 mismatch: ' + record['source_uid'])
    if not record['stem']['text'].strip() and not record['stem']['images']:
        raise ValueError('Missing question stem: ' + record['source_uid'])
    labels = [o['label'] for o in record['options']]
    if len(labels) != len(set(labels)):
        raise ValueError('Duplicate option labels: ' + record['source_uid'])


def load(path, source_id, asset_root, overrides=None, errata=None):
    records = [json.loads(line) for line in Path(path).read_text(encoding='utf8').splitlines() if line.strip()]
    if not records:
        raise ValueError('Source file is empty')
    seen = set()
    for record in records:
        validate(record, asset_root)
        if record['source_id'] != source_id or record['source_uid'] in seen:
            raise ValueError('Source ID mismatch or duplicate source UID')
        seen.add(record['source_uid'])
    if len({r['revision'] for r in records}) != 1:
        raise ValueError('One source revision per import is required')
    corrections = json.loads(Path(overrides).read_text(encoding='utf8')) if overrides else None
    applied, excluded = [], []
    records = deepcopy(records)
    baselines = {r['source_uid']: r.copy() for r in records}
    touched = {}
    if corrections:
        canonical(corrections)
        Draft202012Validator(OVERRIDE_SCHEMA).validate(corrections)
        if (corrections['source_id'], corrections['revision']) != (source_id, records[0]['revision']):
            raise ValueError('Overrides target a different source or revision')
        for entry in corrections['entries']:
            matches = [r for r in records if all(baselines[r['source_uid']].get(k) == v for k, v in entry['match'].items())]
            if not matches:
                raise ValueError('Unmatched override: ' + canonical(entry['match']))
            for record in matches:
                for key, value in entry['set'].items():
                    token = (record['source_uid'], key)
                    if token in touched and touched[token] != value:
                        raise ValueError('Conflicting override: ' + str(token))
                    touched[token] = value
                    applied.append(dict(source_uid=record['source_uid'], field=key, old=record.get(key),
                                        new=value, reason=entry['reason'], evidence=entry['evidence']))
                    record[key] = value
        for record in records:
            if record.pop('exclude', False):
                excluded.append(dict(source_uid=record['source_uid'], bank_id=bank_id(record),
                                     reason='metadata override: exclude'))
            validate(record, asset_root)
    if errata:
        from app.bank.errata import apply
        records,document=apply(records,errata)
        corrections={'overrides':corrections,'errata':document}
        for record in records:validate(record,asset_root)
    return sorted(records, key=lambda r: r['source_uid']), corrections, applied, excluded


def display(record, role):
    content = record[role]['text']
    if role == 'stem':
        content += ''.join('\n\n' + o['label'] + '. ' + o['content']['text'] for o in record['options'])
    return content


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS bank_source_records(
        bank_id TEXT PRIMARY KEY REFERENCES bank_questions(id),source_id TEXT NOT NULL,source_uid TEXT NOT NULL,
        revision TEXT NOT NULL,record_sha256 TEXT NOT NULL,record_json TEXT NOT NULL,overrides_json TEXT NOT NULL,
        UNIQUE(source_id,source_uid))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS bank_source_versions(
        bank_id TEXT NOT NULL REFERENCES bank_questions(id),record_sha256 TEXT NOT NULL,
        record_json TEXT NOT NULL,overrides_json TEXT NOT NULL,created_at TEXT NOT NULL,
        PRIMARY KEY(bank_id,record_sha256))''')

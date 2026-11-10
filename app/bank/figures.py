"""Audited redrawn figures, separate from upstream text and original images."""
import copy,json,re
from pathlib import Path
from io import BytesIO
from PIL import Image
from app.bank import source_records as r

ENTRY=r.obj({'figure_id':{'type':'string','pattern':'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$'},'role':{'enum':['stem','analysis']},
    'image':r.RESOURCE['properties']['images']['items'],'kind':{'const':'redrawn'},'caption':{'const':'按题意重绘'},'reason':r.TEXT,'evidence':r.TEXT})
SUPPLEMENT=r.obj({'entries':{'type':'array','items':ENTRY},'materialized_roles':{'type':'array','uniqueItems':True,'items':{'enum':['stem','analysis']}}})

def check_image(image,root):
    raw=r.asset_path(root,image['path']).read_bytes()
    if len(raw)>8*1024*1024:raise ValueError('figure_image_invalid: 图片最多8MB')
    if r.sha256(raw)!=image['sha256']:raise ValueError('figure_hash_mismatch: '+image['path'])
    with Image.open(BytesIO(raw)) as im:
        if Image.MIME.get(im.format)!=image['media_type'] or im.width*im.height>40_000_000:raise ValueError('figure_image_invalid: 格式或尺寸不符')
        im.verify()
    return raw

def validate(value,root):
    from jsonschema import Draft202012Validator
    Draft202012Validator(SUPPLEMENT).validate(value)
    ids=set()
    for e in value['entries']:
        if e['figure_id'] in ids:raise ValueError('figure_id_conflict: '+e['figure_id'])
        ids.add(e['figure_id']);check_image(e['image'],root)
        if not e['reason'].strip() or not e['evidence'].strip():raise ValueError('figure_schema_invalid: 依据不能为空')

def apply(batch,path,root,collection):
    from jsonschema import Draft202012Validator
    doc=json.loads(Path(path).read_text(encoding='utf8'))
    entry=copy.deepcopy(ENTRY);entry['properties']['match']=r.obj({'source_uid':r.TEXT});entry['required'].append('match')
    schema=r.obj({'schema':{'const':'mathlens.bank-figures/v1'},'source_id':r.TEXT,'revision':r.TEXT,'collection_id':r.TEXT,'entries':{'type':'array','items':entry}})
    Draft202012Validator(schema).validate(doc)
    if (doc['source_id'],doc['revision'],doc['collection_id'])!=(batch[0]['source_id'],batch[0]['revision'],collection):raise ValueError('figure_scope_mismatch: 来源、版本或题集不符')
    by={v['source_uid']:v for v in batch};ids=set()
    for item in doc['entries']:
        if item['figure_id'] in ids:raise ValueError('figure_id_conflict: '+item['figure_id'])
        ids.add(item['figure_id']);uid=item['match']['source_uid']
        if uid not in by:raise ValueError('figure_target_not_found: '+uid)
        e={k:v for k,v in item.items() if k!='match'};check_image(e['image'],root)
        by[uid].setdefault('supplemental_figures',{'entries':[],'materialized_roles':[]})['entries'].append(e)
    for record in batch:
        if 'supplemental_figures' in record:
            record['supplemental_figures']['entries'].sort(key=lambda e:e['figure_id']);validate(record['supplemental_figures'],root)
    return doc

def parts(record,role,asset_root,figure_root=None):
    values=[(record[role],asset_root)]+([(o['content'],asset_root) for o in record['options']] if role=='stem' else [])
    sup=record.get('supplemental_figures',{})
    if role not in sup.get('materialized_roles',[]):
        values += [(r.resource(images=[e['image']]),figure_root or asset_root) for e in sup.get('entries',[]) if e['role']==role]
    return values

def combined(blobs):
    if not blobs:return None
    if len(blobs)==1:return blobs[0]
    images=[]
    for raw in blobs:
        with Image.open(BytesIO(raw)) as im:images.append(im.convert('RGB'))
    canvas=Image.new('RGB',(max(i.width for i in images),sum(i.height for i in images)),'white');y=0
    for im in images:canvas.paste(im,(0,y));y+=im.height;im.close()
    output=BytesIO();canvas.save(output,format='PNG');canvas.close();return output.getvalue()

def material_revision(record,asset_root,figure_root=None):
    result={};ext={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}
    for role in ('stem','answer','analysis'):
        images=[(i,root) for p,root in parts(record,role,asset_root,figure_root) for i in p['images']]
        blobs=[]
        for i,root in images:
            raw=r.asset_path(root,i['path']).read_bytes()
            if r.sha256(raw)!=i['sha256']:raise ValueError('figure_hash_mismatch: '+i['path'])
            blobs.append(raw)
        raw=combined(blobs);sha=r.sha256(raw) if raw else None;text=r.display(record,role)
        if text or sha:
            path='bank-assets/source/'+sha+('.png' if len(blobs)>1 else ext[images[0][0]['media_type']]) if sha else ''
            result['question' if role=='stem' else role]=dict(text=text,path=path,image_sha256=sha,sha256=r.digest(dict(text=text,image_sha256=sha)))
    return r.digest(result)

def markers(conn,bid):
    row=conn.execute('SELECT metadata_json FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()
    value=json.loads(row[0]).get('supplemental_figures',{}) if row else {}
    return [dict(**{k:e[k] for k in ('figure_id','role','kind','caption','reason','evidence')},image_sha256=e['image']['sha256']) for e in value.get('entries',[])]

"""Resolve private files through their saved identities and access policy."""
from app.storage.paths import paper_path, relative_file, resolve_file, connection_data
from dataclasses import dataclass
import json
from pathlib import Path
from app.common import as_json,json_load
from app.errors import ServiceError
from app.bank.access import require_access,record_view
from app.storage.images import image_records,image_path
from app.storage.boundaries import material_path

@dataclass(frozen=True)
class Resource:
    content: bytes|Path
    media_type: str

class ResourceService:
    def __init__(self,config,database):self.config,self.database=config,database

    def evidence_metadata(self,question_id):
        import pymupdf
        with self.database.session() as conn:
            row=conn.execute('SELECT q.regions_json,p.source_path FROM questions q JOIN papers p ON p.id=q.paper_id WHERE q.id=?',(question_id,)).fetchone()
        if not row or not row['source_path']:return []
        pdf=paper_path(self.config.data,row['source_path'],self.config.root)
        if not pdf.is_file():return []
        result=[]
        with pymupdf.open(pdf) as doc:
            for i,region in enumerate(json_load(row['regions_json'],[])):
                pix=doc[region['page']-1].get_pixmap(matrix=pymupdf.Matrix(2,2),clip=pymupdf.Rect(region['bbox']),alpha=False)
                result.append(dict(region_index=i,page=region['page'],bbox=region['bbox'],
                    image_url=f'/api/questions/{question_id}/evidence?region={i}',image_width=pix.width,image_height=pix.height,
                    image_origin=[pix.x,pix.y],scale=2))
        return result
    def answer(self,image_id):
        try:
            with self.database.session() as conn:record=image_records(conn,[image_id])[0]
            return Resource(image_path(record,self.config.data),'image/jpeg')
        except ValueError as e:raise ServiceError(str(e),404) from None
    def paper(self,paper_id):
        with self.database.session() as conn:row=conn.execute('SELECT source_path FROM papers WHERE id=?',(paper_id,)).fetchone()
        if not row or not row[0]:raise ServiceError('paper file not found',404)
        path=paper_path(self.config.data,row[0],self.config.root)
        if not path.is_relative_to(self.config.papers) or not path.is_file():raise ServiceError('paper file not found',404)
        return Resource(path,'application/pdf')
    def bank(self,bank_id,role,library=False,probe_id=None):
        if role not in ('question','analysis','answer'):raise ServiceError('资源类别不合法',404)
        with self.database.session(write=True) as conn:
            try:
                if not library:require_access(conn,bank_id,role)
            except ValueError as e:raise ServiceError(str(e),403) from None
            if probe_id is not None:
                if library:raise ServiceError('题库浏览与练习快照入口不能混用',400)
                probe=conn.execute('SELECT bank_id,paper_id FROM diagnostic_probes WHERE id=?',(probe_id,)).fetchone()
                if not probe or probe['bank_id']!=bank_id:raise ServiceError('练习与题库来源不一致',404)
                from app.learning.practice_knowledge import binding_for
                binding=binding_for(conn,probe_id)
                if not binding:
                    from app.learning.plans import practice_state
                    state=practice_state(conn,probe['paper_id'])
                    if any(item['probe_id']==probe_id for item in state.get('deferred_probes',[])):
                        raise ServiceError('旧练习原题版本待核，不能用当前题库材料代替；历史作答保留',409)
                if binding:
                    try:
                        from app.storage.practice_materials import image_path,load
                        manifest=load(self.config.data,binding['snapshot_key'],binding['snapshot_sha256'],(role,))
                        item=manifest['resources'].get(role)
                        if item and not item['image_file'] and item['text']:
                            record_view(conn,bank_id,role)
                            return Resource(json.dumps({'bank_id':bank_id,'role':role,'text':item['text'],
                                'sha256':item['sha256']},ensure_ascii=False).encode('utf8'),'application/json')
                        path=image_path(self.config.data,binding,role)
                    except ValueError as error:raise ServiceError(str(error),404) from None
                    record_view(conn,bank_id,role)
                    media={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}.get(path.suffix.lower(),'image/png')
                    return Resource(path,media)
            row=conn.execute('SELECT * FROM bank_resources WHERE bank_id=?',(bank_id,)).fetchone()
            if row and row[role+'_path']:
                path=material_path(self.config.data,row[role+'_path']).resolve()
                if path.is_relative_to((self.config.library_dir/'bank-assets').resolve()) and path.is_file():
                    record_view(conn,bank_id,role)
                    return Resource(path,'image/png')
            if row and not row[role+'_path']:
                from app.bank.annotations import materials
                item=materials(conn,self.config.data,bank_id).get(role)
                if item and item['text']:
                    record_view(conn,bank_id,role)
                    return Resource(json.dumps({'bank_id':bank_id,'role':role,'text':item['text'],
                        'sha256':item['sha256']},ensure_ascii=False).encode('utf8'),'application/json')
        raise ServiceError('题库资源缺失',404)
    def evidence(self,question_id,index=0):
        import pymupdf
        if index<0:raise ServiceError('证据区域不存在',404)
        with self.database.session() as conn:row=conn.execute('SELECT q.regions_json,p.source_path FROM questions q JOIN papers p ON p.id=q.paper_id WHERE q.id=?',(question_id,)).fetchone()
        if not row:raise ServiceError('题目不存在',404)
        try:
            region=json_load(row['regions_json'],[])[index]
            pdf=paper_path(self.config.data,row['source_path'],self.config.root)
            if not pdf.is_relative_to(self.config.papers):raise ValueError('invalid file')
            with pymupdf.open(pdf) as doc:raw=doc[region['page']-1].get_pixmap(matrix=pymupdf.Matrix(2,2),clip=pymupdf.Rect(region['bbox']),alpha=False).tobytes('png')
            return Resource(raw,'image/png')
        except (ValueError,IndexError,KeyError,TypeError):raise ServiceError('证据区域不存在',404) from None

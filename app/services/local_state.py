"""Durable UI drafts and local maintenance, separate from learning evidence."""
import hashlib,json,uuid
from pathlib import Path
from app.common import json_load
from app.storage.maintenance import backup,cleanup_images,restore
from app.documents.progress import list_progress

class LocalStateService:
    def __init__(self,config,database):self.config,self.database=config,database
    def screen(self):
        path=self.config.data/'screen.json';return json_load(path.read_text(encoding='utf8'),{}) if path.is_file() else {}
    def save_screen(self,body):
        if len(json.dumps(body))>6000:raise ValueError('页面上下文过长')
        (self.config.data/'screen.json').write_text(json.dumps(body,ensure_ascii=False),encoding='utf8');return {'ok':True}
    def draft(self,key):
        path=self.config.data/'drafts'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
        return json_load(path.read_text(encoding='utf8'),{}) if path.is_file() else {}
    def save_draft(self,body):
        key,value=body.get('key'),body.get('value')
        if not isinstance(key,str) or len(key)>300 or len(json.dumps(value))>120000:raise ValueError('草稿过长或标识不合法')
        folder=self.config.data/'drafts';folder.mkdir(exist_ok=True)
        path=folder/(hashlib.sha256(key.encode()).hexdigest()+'.json');temp=folder/(uuid.uuid4().hex+'.tmp')
        temp.write_text(json.dumps({'key':key,'value':value},ensure_ascii=False),encoding='utf8');temp.replace(path);return {'ok':True}
    def preparation(self):return {'items':list_progress(self.config.data)}
    def backups(self):return {'backups':[{'name':p.name,'bytes':p.stat().st_size} for p in sorted((self.config.data/'backups').glob('*.zip'),reverse=True)]}
    def backup(self):return backup(self.config.data,self.config.root)
    def cleanup(self):
        with self.database.session(write=True) as conn:return cleanup_images(conn,self.config.data)
    def restore(self,name,library_dir=None,confirm_older_library=False):
        archive=self.config.data/'backups'/Path(name).name
        if archive.parent.resolve()!=(self.config.data/'backups').resolve() or not archive.is_file() or archive.suffix!='.zip':raise ValueError('本地备份不存在')
        return restore(archive,self.config.data.parent/('mathlens-restored-'+uuid.uuid4().hex[:8]),library_dir=library_dir,confirm_older_library=confirm_older_library)

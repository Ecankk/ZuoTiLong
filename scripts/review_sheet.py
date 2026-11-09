"""Export selected library questions for private, offline human review.

Requires explicit MATHLENS_LIBRARY_DIR. No application initialization or DB writes.
Feedback is an array in feedback.json; verdict: consistent / error / uncertain.
Notes accepts an array of {bank_id, checks: [text], errata: [{find,replace,...}]}.
Run with --serve for durable autosave and photo uploads; Ctrl+C stops the server.
"""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from io import BytesIO
import json
import mimetypes
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
from urllib.parse import parse_qs,unquote,urlsplit
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.bank import annotations
from app.bank.annotation_view import AnnotationReadView
from app.knowledge import catalog
from app.storage.paths import resolve_file


def bank_ids(value):
    path=Path(value)
    if ',' not in value and path.is_file():
        text=path.read_text(encoding='utf-8-sig')
        values=json.loads(text) if text.lstrip().startswith('[') else text.replace(',','\n').splitlines()
    else:values=value.split(',')
    if not isinstance(values,list) or any(not isinstance(v,str) for v in values):raise ValueError('bank-ids 须为 ID 数组或逗号/换行列表')
    result=list(dict.fromkeys(v.strip() for v in values if v.strip()))
    if not result:raise ValueError('至少指定一道题')
    return result


def load_notes(path):
    if path is None:return {}
    value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if isinstance(value,dict):
        value=value.get('items',value)
        if isinstance(value,dict):value=[dict(v,bank_id=k) for k,v in value.items()]
    if not isinstance(value,list):raise ValueError('notes 须为条目数组、items 数组或以 bank_id 为键的对象')
    result={}
    for item in value:
        if not isinstance(item,dict) or not isinstance(item.get('bank_id'),str) or item['bank_id'] in result:raise ValueError('notes 条目须有唯一 bank_id')
        result[item['bank_id']]=item
    return result


def copy_asset(library,output,item):
    path=resolve_file(library,item['path'])
    if not path.is_relative_to((library/'bank-assets').resolve()):raise ValueError('题库图片路径越界')
    raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if item.get('sha256') and item['sha256']!=sha:raise ValueError('图片散列不符：'+item['path'])
    suffix=path.suffix.lower()
    if suffix not in ('.png','.jpg','.jpeg','.webp'):raise ValueError('不支持的题图类型')
    relative='assets/'+sha+suffix;target=output/relative
    target.parent.mkdir(exist_ok=True);target.write_bytes(raw)
    return relative


def read_cards(library,collection,ids,output,notes):
    """One explicit read transaction, attached to no personal workspace."""
    cards=[]
    with closing(sqlite3.connect((library/'library.db').as_uri()+'?mode=ro',uri=True)) as conn:
        conn.row_factory=sqlite3.Row;conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        group=conn.execute('SELECT * FROM bank_collections WHERE id=?',(collection,)).fetchone()
        if not group:raise ValueError('题集不存在：'+collection)
        view=AnnotationReadView(conn,library)
        def topic(binding):
            tid=view.resolve(binding['topic_id']);node=view.nodes.get(tid);parts=[];seen=set()
            while node and node['id'] not in seen:
                seen.add(node['id']);parts.append(node['name']);node=view.nodes.get(node['parent_id'])
            return dict(binding,name=view.nodes[tid]['name'] if tid in view.nodes else binding['topic_id'],path=' / '.join(reversed(parts)))
        for bid in ids:
            row=conn.execute('SELECT * FROM bank_questions WHERE id=?',(bid,)).fetchone()
            if not row or row['collection_id']!=collection:raise ValueError('题目不存在或不属于指定题集：'+bid)
            packed=conn.execute('SELECT * FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()
            meta=json.loads(packed['metadata_json']) if packed else {}
            source=conn.execute('SELECT record_json FROM bank_source_records WHERE bank_id=?',(bid,)).fetchone()
            source=json.loads(source[0]) if source else None
            material=view.materials(bid)
            annotation=annotations.current(conn,library,bid,read_view=view)
            analysis=annotation['analysis'] if annotation else {}
            state=analysis.get('status') or meta.get('annotation_status') or 'unannotated'
            if not annotation and conn.execute('SELECT 1 FROM question_annotation_links WHERE bank_id=?',(bid,)).fetchone():state='outdated'
            roles={}
            for role in ('question','answer','analysis'):
                item=material.get(role,{})
                images=meta.get('resources',{}).get(role,{}).get('images',[])
                if not images and item.get('path'):images=[dict(path=item['path'],sha256=item['image_sha256'])]
                roles[role]=dict(text=item.get('text',''),images=list(dict.fromkeys(copy_asset(library,output,i) for i in images)))
            # Standard stem/options remain separate. Role images include all original
            # illustrations, including option images (not only a display derivative).
            options=[]
            if source:
                roles['question']['text']=source['stem']['text']
                options=[dict(label=o['label'],text=o['content']['text']) for o in source['options']]
            identity=conn.execute('SELECT * FROM bank_identity WHERE bank_id=?',(bid,)).fetchone()
            book=meta.get('book') or (source or {}).get('book') or {}
            label=' / '.join(str(book[k]) for k in ('title','part','chapter','number','locator') if book.get(k))
            if not label and identity:label=f"{identity['year']} 数学{identity['math_type']} 第{identity['number']}题"
            check=analysis.get('answer_check') or {}
            cards.append(dict(bank_id=bid,collection_id=collection,collection_name=group['name'],location=label or row['source_ref'] or bid,
                material_sha256=catalog.digest(material),resources=roles,options=options,status=state,
                review_note=analysis.get('review_note') or check.get('note') or meta.get('review_note') or '',
                topics=[topic(b) for b in analysis.get('bindings',[])],notes=notes.get(bid),errata=meta.get('errata',[])))
    return cards


def copy_math(output):
    """Use the actual frontend tokenizer and KaTeX version, without a CDN."""
    modules=ROOT/'web/node_modules';dist=modules/'katex/dist'
    if not (dist/'katex.min.js').is_file():raise ValueError('缺少 web/node_modules/katex；请先 npm --prefix web ci')
    node=shutil.which('node')
    if not node:raise ValueError('需要本机 Node.js 编译前端公式分隔符规则')
    source=ROOT/'web/src/lib/math.ts'
    code="const fs=require('fs'),ts=require(process.argv[1]);let s=ts.transpileModule(fs.readFileSync(process.argv[2],'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.ESNext}}).outputText;process.stdout.write(s.replace(/^export /gm,''));"
    compiled=subprocess.run([node,'-e',code,str(modules/'typescript'),str(source)],capture_output=True,text=True,encoding='utf8',check=True).stdout
    vendor=output/'vendor';vendor.mkdir(exist_ok=True)
    shutil.copytree(dist,vendor/'katex',dirs_exist_ok=True)
    (vendor/'math.js').write_text(compiled,encoding='utf8')


def generate(library,collection,ids,output,notes=None):
    library=Path(library).resolve();output=Path(output).resolve()
    if output.is_relative_to(library) or output.is_relative_to(ROOT):raise ValueError('输出必须为仓库和通用库以外的私有目录')
    if not (library/'library.db').is_file():raise ValueError('显式指定的通用库不存在')
    output.mkdir(parents=True,exist_ok=True)
    copy_math(output)
    cards=read_cards(library,collection,ids,output,load_notes(notes))
    feedback=FeedbackStore(output,cards).read()
    payload=json.dumps(dict(cards=cards,feedback=feedback),ensure_ascii=False).replace('<','\\u003c')
    (output/'sheet-data.js').write_text('const SHEET='+payload+';\n',encoding='utf8')
    (output/'index.html').write_text(Path(__file__).with_name('review_sheet.html').read_text(encoding='utf8'),encoding='utf8')
    return cards


class FeedbackStore:
    def __init__(self,output,cards):
        self.output=Path(output);self.cards={c['bank_id']:c for c in cards};self.lock=threading.RLock()
    def read(self):
        with self.lock:
            path=self.output/'feedback.json'
            rows=json.loads(path.read_text(encoding='utf8')) if path.exists() else []
            if not isinstance(rows,list):raise ValueError('feedback.json 须为数组')
            for row in rows:
                if row['bank_id'] not in self.cards or row['material_sha256']!=self.cards[row['bank_id']]['material_sha256']:
                    raise ValueError('已有反馈与本次题目/材料版本不一致；请使用另一个输出目录')
            return rows
    def validate(self,bid,sha):
        if bid not in self.cards or sha!=self.cards[bid]['material_sha256']:raise ValueError('题目或材料版本不一致')
    def update(self,bid,sha,*,verdict=None,note=None,photo=None):
        self.validate(bid,sha)
        if verdict is not None and verdict not in ('','consistent','error','uncertain'):raise ValueError('核对结论不合法')
        if note is not None and (not isinstance(note,str) or len(note)>20000):raise ValueError('意见须为不超过20000字的文字')
        with self.lock:
            rows=self.read();row=next((r for r in rows if r['bank_id']==bid),None)
            if row is None:
                row=dict(bank_id=bid,material_sha256=sha,verdict='',note='',photos=[],updated_at='');rows.append(row)
            if verdict is not None:row['verdict']=verdict
            if note is not None:row['note']=note
            if photo:row['photos'].append(photo)
            row['updated_at']=datetime.now(timezone.utc).isoformat()
            temporary=self.output/('feedback-'+uuid.uuid4().hex+'.tmp')
            try:
                temporary.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
                os.replace(temporary,self.output/'feedback.json')
            finally:temporary.unlink(missing_ok=True)
            return row
    def photo(self,bid,sha,raw):
        from PIL import Image,ImageOps
        self.validate(bid,sha)
        if not raw or len(raw)>10*1024*1024:raise ValueError('照片最大10MB')
        with Image.open(BytesIO(raw)) as image:
            if image.format not in ('JPEG','PNG','WEBP') or image.width*image.height>40_000_000:raise ValueError('仅接受PNG/JPEG/WebP照片，最多4000万像素')
            image=ImageOps.exif_transpose(image).convert('RGB')
            folder=self.output/'photos';folder.mkdir(exist_ok=True)
            name='photos/'+uuid.uuid4().hex+'.jpg';image.save(self.output/name,'JPEG',quality=92)
        return self.update(bid,sha,photo=name)


def make_server(output,cards):
    output=Path(output).resolve();store=FeedbackStore(output,cards)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,value,status=200):
            raw=json.dumps(value,ensure_ascii=False).encode('utf8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if urlsplit(self.path).path=='/state':return self.respond(store.read())
            try:
                path=resolve_file(output,unquote(urlsplit(self.path).path).lstrip('/') or 'index.html')
                if not path.is_file():return self.send_error(404)
                raw=path.read_bytes()
            except (ValueError,OSError):return self.send_error(404)
            self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
        def do_POST(self):
            origin=f'http://127.0.0.1:{self.server.server_port}'
            if self.headers.get('Origin')!=origin:return self.respond({'error':'仅接受本机核对页的同源请求'},403)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=10*1024*1024:return self.respond({'error':'请求大小须为1字节至10MB'},413)
                raw=self.rfile.read(length);path=urlsplit(self.path)
                if path.path=='/feedback':
                    value=json.loads(raw)
                    result=store.update(value['bank_id'],value['material_sha256'],verdict=value['verdict'],note=value['note'])
                elif path.path=='/photos':
                    query=parse_qs(path.query)
                    result=store.photo(query['bank_id'][0],query['material_sha256'][0],raw)
                else:return self.respond({'error':'接口不存在'},404)
                self.respond(result)
            except (ValueError,KeyError,TypeError,OSError) as error:self.respond({'error':str(error)},400)
    return ThreadingHTTPServer(('127.0.0.1',0),Handler)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection',required=True);parser.add_argument('--bank-ids',required=True)
    parser.add_argument('--notes',type=Path);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--serve',action='store_true')
    args=parser.parse_args()
    selected=os.environ.get('MATHLENS_LIBRARY_DIR')
    if not selected:parser.error('必须显式设置 MATHLENS_LIBRARY_DIR，不使用默认工作区')
    cards=generate(Path(selected),args.collection,bank_ids(args.bank_ids),args.output,args.notes)
    print(json.dumps(dict(output=str(args.output.resolve()),questions=len(cards)),ensure_ascii=False),flush=True)
    if args.serve:
        with make_server(args.output,cards) as http:
            print(f'http://127.0.0.1:{http.server_port}/',flush=True)
            try:http.serve_forever()
            except KeyboardInterrupt:pass


if __name__=='__main__':main()

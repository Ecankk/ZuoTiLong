"""Opt-in, expiring LAN upload inbox. Never exposes the app, files or Agent."""
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import secrets
import socket
import threading
import time

from answer_images import save_answer_image


class MobileInbox:
    def __init__(self,connect,data,write_guard):
        self.connect,self.data,self.write_guard=connect,data,write_guard
        self.lock=threading.RLock();self.http=None;self.token=None;self.images=[];self.expires=0;self.target=''

    def stop(self,expected_token=None):
        with self.lock:
            if expected_token and self.token!=expected_token:return self.state()
            server=self.http;self.http=None;self.token=None;self.expires=0
        if server:server.shutdown();server.server_close()
        return {'active':False}

    def state(self):
        with self.lock:return {'active':bool(self.http and time.time()<self.expires),'target':self.target,'expires_at':self.expires,'images':self.images}

    def start(self,target,host='0.0.0.0'):
        if not isinstance(target,str) or not target or len(target)>250:raise ValueError('上传目标不合法')
        self.stop();inbox=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,code,content,kind='text/html; charset=utf-8'):
                raw=content.encode('utf8');self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(raw)
            def valid(self):return inbox.token and self.path=='/'+inbox.token+'/' and time.time()<inbox.expires
            def do_GET(self):
                if not self.valid():self.reply(404,'链接无效或已过期');return
                self.reply(200,'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>MathLens 传图</title><style>body{font:18px system-ui;padding:24px;background:#eef6f2}input,button{font-size:18px;margin:16px 0}button{padding:12px}</style><h1>上传本次手写作答</h1><p>只接收照片，不开放试卷、画像或 Codex。链接 10 分钟后失效。</p><form method="post" enctype="multipart/form-data"><input type="file" name="files" accept="image/jpeg,image/png,image/webp" multiple required><br><button>上传到电脑</button></form><p>最多 4 张，每张 8 MB；拍照后也可从相册选择。</p>')
            def do_POST(self):
                if not self.valid():self.reply(404,'链接无效或已过期');return
                try:
                    origin=self.headers.get('Origin')
                    if origin and origin!='http://'+self.headers.get('Host',''):raise ValueError('来源不合法')
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=33*1024*1024:raise ValueError('大小不合法')
                    content_type=self.headers.get('Content-Type','')
                    if 'multipart/form-data' not in content_type:raise ValueError('请选择照片')
                    message=BytesParser(policy=default).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+self.rfile.read(length))
                    files=[part.get_payload(decode=True) for part in message.iter_parts() if part.get_param('name',header='content-disposition')=='files']
                    with inbox.write_guard(),inbox.lock:
                        if not self.valid():raise ValueError('链接已过期，请重新开启')
                        if not 1<=len(files)<=4 or len(files)+len(inbox.images)>4:raise ValueError('本次传图最多 4 张')
                        conn=inbox.connect()
                        try:
                            with conn:assets=[save_answer_image(conn,inbox.data,raw) for raw in files]
                        finally:conn.close()
                        inbox.images.extend(asset for asset in assets if asset['id'] not in {i['id'] for i in inbox.images})
                    self.reply(200,'<meta charset="utf-8"><h2>已传到电脑，请回到 MathLens 预览并提交。</h2><p>照片尚未作为作答发送给 Agent。</p>')
                except ValueError as exc:self.reply(400,str(exc),'text/plain; charset=utf-8')
        with self.lock:
            self.token=secrets.token_urlsafe(32);self.target=target;self.images=[];self.expires=time.time()+600
            self.http=ThreadingHTTPServer((host,0),Handler);self.http.daemon_threads=True;port=self.http.server_address[1]
            threading.Thread(target=self.http.serve_forever,daemon=True).start()
            timer=threading.Timer(600,self.stop,args=(self.token,));timer.daemon=True;timer.start()
            addresses=sorted({v[4][0] for v in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET) if not v[4][0].startswith('127.')})
            return {**self.state(),'urls':[f'http://{ip}:{port}/{self.token}/' for ip in addresses or ['127.0.0.1']]}

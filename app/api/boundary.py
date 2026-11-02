"""Local origin and request-size boundary, before JSON or multipart parsing."""
from urllib.parse import urlparse
from starlette.responses import JSONResponse

class BodyTooLarge(ValueError):pass

class LocalBoundary:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        path=scope.get('path','');headers=dict(scope.get('headers',[]));api=path.startswith('/api/')
        host=headers.get(b'host',b'').decode();origin=headers.get(b'origin',b'').decode()
        if api and (urlparse('http://'+host).hostname not in ('127.0.0.1','localhost','::1') or scope['method'] not in ('GET','HEAD','OPTIONS') and origin and origin!='http://'+host):
            return await JSONResponse({'error':'只接受本地网页的同源请求'},status_code=403)(scope,receive,send)
        limit=80*1024*1024 if path=='/api/papers/import' else 33*1024*1024 if path=='/api/answer-images' else 16*1024*1024 if path in ('/api/knowledge/packages/preview','/api/knowledge/packages/import','/api/knowledge/question-index/preview','/api/knowledge/question-index/import') else 100000 if path.startswith('/api/agent/') else 1024*1024
        try:length=int(headers.get(b'content-length',b'0'))
        except ValueError:return await JSONResponse({'error':'无效的请求长度'},status_code=400)(scope,receive,send)
        if length>limit:return await JSONResponse({'error':'请求或上传文件过大'},status_code=400)(scope,receive,send)
        consumed=0
        async def bounded_receive():
            nonlocal consumed
            message=await receive();consumed+=len(message.get('body',b''))
            if consumed>limit:raise BodyTooLarge('请求或上传文件过大')
            return message
        async def private_send(message):
            if api and message['type']=='http.response.start':
                outgoing=list(message.get('headers',[]))
                if not any(k.lower()==b'cache-control' for k,v in outgoing):outgoing.append((b'cache-control',b'no-store'))
                message={**message,'headers':outgoing+[(b'x-content-type-options',b'nosniff')]}
            await send(message)
        await self.app(scope,bounded_receive,private_send)

"""Exercise the actual Windows frozen exe against synthetic, isolated data."""
import argparse
from contextlib import contextmanager
import io,json,os,queue,re,secrets,shutil,subprocess,sys,tempfile,threading,time
from pathlib import Path
from urllib.request import Request,ProxyHandler,build_opener


@contextmanager
def readonly(directory):
    who=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],encoding='utf8',errors='replace')
    sid=re.search(r'S-1-\d+(?:-\d+)+',who)[0]
    subprocess.run(['icacls',str(directory),'/deny','*'+sid+':(OI)(CI)(WD,AD,WEA,WA,DC)'],check=True,capture_output=True)
    try:
        try:(directory/'must-not-write').write_text('bad')
        except PermissionError:pass
        else:raise AssertionError('Read-only ACL did not block writes')
        yield
    finally:subprocess.run(['icacls',str(directory),'/remove:d','*'+sid,'/t','/c'],check=True,capture_output=True)


def multipart(files):
    boundary='MathLens'+secrets.token_hex(16);parts=[]
    for field,name,mime,content in files:
        parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+field+'"; filename="'+name+'"\r\nContent-Type: '+mime+'\r\n\r\n').encode()+content+b'\r\n')
    return b''.join(parts)+('--'+boundary+'--\r\n').encode(),'multipart/form-data; boundary='+boundary


def run(stage,output):
    if os.name!='nt':raise RuntimeError('Windows x64 smoke only')
    import pymupdf
    from PIL import Image
    output.mkdir(parents=True,exist_ok=True);installed=output/'安装 中文 space';shutil.copytree(stage,installed)
    resources=installed/'resources';exe=installed/'backend/mathlens-backend.exe'
    data=output/'个人 数据/workspaces/default';library=output/'个人 数据/library';decoys=output/'继承诱饵'
    env=os.environ.copy();env.update(MATHLENS_DATA_DIR=str(decoys/'data'),MATHLENS_LIBRARY_DIR=str(decoys/'library'),MATHLENS_DIST_DIR=str(decoys/'dist'),MATHLENS_DEMO='1',
        MATHLENS_CODEX_BIN=str(output/'不存在的codex.exe'),MATHLENS_PACKAGING_OFFLINE_SMOKE='1',PYTHONUTF8='1',PATH=os.path.join(os.environ['SystemRoot'],'System32'))
    env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
    result=dict(exe=str(exe),offline='Python external sockets denied; ORT telemetry disabled; OS firewall not modified',python_on_child_path=False,resources_readonly=True,operations={})
    with pymupdf.open() as doc:
        page=doc.new_page();page.insert_text((40,80),'1. Calculate one plus one.',fontsize=20)
        digital=doc.tobytes();pixels=page.get_pixmap(matrix=pymupdf.Matrix(2,2)).tobytes('png')
    with pymupdf.open() as doc:
        page=doc.new_page();page.insert_image(page.rect,stream=pixels);scanned=doc.tobytes()
    with readonly(installed):
        for mode in ('prepare-desktop','desktop'):
            nonce=secrets.token_hex(32);command=[str(exe),'--'+mode,'--resource-root',str(resources),'--data-dir',str(data),'--library-dir',str(library),'--launch-nonce',nonce]
            messages=queue.Queue();lines=[];stderr=(output/(mode+'.stderr.log')).open('w',encoding='utf8');start=time.perf_counter()
            child=subprocess.Popen(command,cwd=output,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,text=True,encoding='utf8')
            def reader():
                try:
                    for line in child.stdout:messages.put(json.loads(line))
                except Exception as exc:messages.put(exc)
                finally:messages.put(None)
            thread=threading.Thread(target=reader,daemon=True);thread.start()
            try:
                end=time.monotonic()+180
                while True:
                    try:item=messages.get(timeout=1)
                    except queue.Empty:
                        if time.monotonic()>end:raise TimeoutError('Frozen startup exceeded 180 seconds')
                        continue
                    if isinstance(item,Exception):raise item
                    if item is None:raise RuntimeError('Frozen exe ended before expected event; see '+str(output/(mode+'.stderr.log')))
                    lines.append(item)
                    if item['event']=='error':raise RuntimeError(str(item['error']))
                    if mode=='prepare-desktop' and item['event']=='prepared':
                        result['prepare_seconds']=time.perf_counter()-start;break
                    if mode=='desktop' and item['event']=='address_published':
                        address=item['server'];http=build_opener(ProxyHandler({}));url=address['url']
                        for _ in range(100):
                            try:
                                with http.open(url+'api/health',timeout=2) as response:health=json.load(response)
                                break
                            except OSError:time.sleep(.03)
                        else:raise RuntimeError('Frozen health not ready')
                        assert health['pid']==address['pid'] and health['nonce']==nonce and health['data_id']==address['data_id']
                        result['process_cold_health_seconds']=time.perf_counter()-start;result['health']=health
                        def request(path,files=None):
                            body,mime=multipart(files) if files else (None,None);headers={'Content-Type':mime} if mime else {}
                            t=time.perf_counter()
                            with http.open(Request(url+path,data=body,headers=headers),timeout=90) as r:
                                content=r.read();status=r.status;typ=r.headers.get('Content-Type','');nosniff=r.headers.get('X-Content-Type-Options')
                            return content,dict(status=status,seconds=time.perf_counter()-t,content_type=typ,nosniff=nosniff)
                        for name,content in (('digital',digital),('scanned',scanned)):
                            raw,info=request('api/papers/import',[('file',name+'.pdf','application/pdf',content)]);paper=json.loads(raw)
                            assert info['status']==201 and paper['agent_queued'] is False,(info,paper)
                            info['engine']=paper['paper']['analysis_engine'];info['questions']=paper.get('created_questions');result['operations'][name]=info
                            if name=='scanned':assert 'rapidocr_onnxruntime' in info['engine'],paper
                            raw,_=request('api/papers/'+paper['paper']['id']+'/questions');qid=json.loads(raw)['items'][0]['id']
                            raw,info=request('api/questions/'+qid+'/evidence');assert raw.startswith(b'\x89PNG') and info['nosniff']=='nosniff'
                            result['operations'][name+'_evidence']=info
                        for fmt in ('JPEG','PNG','WEBP'):
                            stream=io.BytesIO();Image.new('RGB',(12,12),'blue').save(stream,format=fmt)
                            raw,info=request('api/answer-images',[('files','image.'+fmt.lower(),'image/'+fmt.lower(),stream.getvalue())]);image=json.loads(raw)['images'][0]
                            raw,served=request('api/answer-images/'+image['id']);assert raw.startswith(b'\xff\xd8') and served['nosniff']=='nosniff'
                            result['operations']['decode_'+fmt]=info
                        raw,info=request('api/tasks');availability=json.loads(raw)['availability'];assert availability['reason']=='not_installed';result['availability']=availability
                        request('');request('topics/GS-01-073.higher-order-infinitesimal');request('api/bank?limit=20')
                        result['ocr_cache_bytes']=sum(p.stat().st_size for p in (data/'ocr-cache').rglob('*') if p.is_file())
                        child.stdin.write(json.dumps(dict(protocol='mathlens.desktop/v1',command='shutdown',nonce=nonce))+'\n');child.stdin.flush()
                        break
                if mode=='desktop':
                    while True:
                        item=messages.get(timeout=12)
                        if item is None:break
                        if isinstance(item,Exception):raise item
                        lines.append(item)
                    assert any(x['event']=='stopped' for x in lines)
                child.wait(timeout=12);assert child.returncode==0,child.returncode
                result[mode+'_exit_code']=child.returncode
            finally:
                if not child.stdin.closed:child.stdin.close()
                if child.poll() is None:child.kill();child.wait(timeout=5)
                thread.join(timeout=5);child.stdout.close();stderr.close()
                (output/(mode+'.jsonl')).write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in lines)+'\n',encoding='utf8')
    assert not decoys.exists();assert not (data/'server.json').exists();assert not list(output.rglob('desktop.json'))
    moved=library/'renamed.db';(library/'library.db').rename(moved);moved.rename(library/'library.db')
    result.update(decoy_entries=0,backend_bytes=sum(p.stat().st_size for p in (stage/'backend').rglob('*') if p.is_file()),resource_bytes=sum(p.stat().st_size for p in (stage/'resources').rglob('*') if p.is_file()))
    (output/'smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(dict(output=str(output),**result),ensure_ascii=False))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stage',type=Path,default=Path(__file__).resolve().parents[2]/'build/desktop-stage');parser.add_argument('--output',type=Path)
    args=parser.parse_args();run(args.stage,args.output or Path(tempfile.mkdtemp(prefix='zuotilong-frozen-smoke-')))

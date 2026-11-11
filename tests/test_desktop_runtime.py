from contextlib import contextmanager
import io,json,os,queue,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import desktop_fixture as fixture
from app.desktop.config import settings
from app.desktop.protocol import Protocol
from app.desktop.prepare import prepare
from app.desktop.control import ParentControl,PROTOCOL

ROOT=Path(__file__).resolve().parents[1]


class DesktopRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        self.root=fixture.resources(self.base);self.args=fixture.arguments(self.base,self.root)
        self.env=os.environ.copy();self.decoy=self.base/'继承 诱饵'
        self.env.update(MATHLENS_DATA_DIR=str(self.decoy/'data'),MATHLENS_LIBRARY_DIR=str(self.decoy/'library'),MATHLENS_DIST_DIR=str(self.decoy/'dist'),MATHLENS_DEMO='1',MATHLENS_CODEX_BIN=str(self.base/'missing-codex.exe'))

    def command(self,mode):
        return [sys.executable,'-X','utf8','-c','import sys;sys.path.insert(0,'+repr(str(ROOT))+');'+getattr(self,'bootstrap','')+'from app.cli import main;raise SystemExit(main())',mode,
            '--resource-root',self.args.resource_root,'--data-dir',self.args.data_dir,'--library-dir',self.args.library_dir,'--launch-nonce',self.args.launch_nonce]

    @contextmanager
    def child(self,mode):
        err=(self.base/'child.stderr').open('w+',encoding='utf8')
        p=subprocess.Popen(self.command(mode),cwd=self.base,env=self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf8')
        messages=queue.Queue()
        def reader():
            for line in p.stdout:messages.put(json.loads(line))
        thread=threading.Thread(target=reader,daemon=True);thread.start()
        try:yield p,messages
        finally:
            if p.stdin and not p.stdin.closed:p.stdin.close()
            try:p.wait(timeout=12)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
            thread.join(timeout=5);p.stdout.close();err.close()
            self.assertFalse(self.decoy.exists())

    def until(self,messages,event):
        end=time.monotonic()+45;items=[]
        while time.monotonic()<end:
            try:value=messages.get(timeout=1)
            except queue.Empty:continue
            items.append(value)
            if value['event']==event:return value,items
        self.fail('No '+event)

    def test_real_prepare_serve_health_shutdown_and_eof_from_arbitrary_cwd(self):
        with self.child('--prepare-desktop') as (p,events):
            value,_=self.until(events,'prepared');self.assertTrue(value['workspace_ready']);self.assertEqual(p.wait(timeout=10),0)
        for command in ('shutdown','eof'):
            with self.child('--desktop') as (p,events):
                value,seen=self.until(events,'address_published');address=value['server']
                from urllib.request import build_opener,ProxyHandler
                http=build_opener(ProxyHandler({}));end=time.monotonic()+10
                while True:
                    try:
                        with http.open(address['url']+'api/health',timeout=1) as response:health=json.load(response)
                        break
                    except OSError:
                        if time.monotonic()>end:raise
                        time.sleep(.02)
                self.assertEqual(health['nonce'],self.args.launch_nonce);self.assertEqual(health['pid'],address['pid'])
                self.assertIn('prepare_navigation',[x['phase'] for x in seen])
                with http.open(address['url']) as r:self.assertIn(b'synthetic desktop',r.read())
                if command=='shutdown':
                    p.stdin.write(json.dumps(dict(protocol=PROTOCOL,command='shutdown',nonce=self.args.launch_nonce))+'\n');p.stdin.flush()
                else:p.stdin.close()
                self.until(events,'stopped');self.assertEqual(p.wait(timeout=10),0)
            self.assertFalse((Path(self.args.data_dir)/'server.json').exists())
            db=Path(self.args.library_dir)/'library.db';other=db.with_suffix('.rename');db.rename(other);other.rename(db)

    def test_parent_eof_before_startup_cancels_without_creating_data(self):
        with self.child('--prepare-desktop') as (p,events):
            p.stdin.close();value,_=self.until(events,'error')
            self.assertEqual(value['error']['code'],'cancelled');self.assertEqual(p.wait(timeout=10),130)

    def test_invalid_cli_and_bad_seed_use_json_exit_codes_without_inherited_paths(self):
        self.args.resource_root='relative'
        with self.child('--prepare-desktop') as (p,events):
            error,_=self.until(events,'error');self.assertEqual(error['error']['code'],'invalid_path');self.assertEqual(p.wait(timeout=10),2)
        self.args=fixture.arguments(self.base,self.root)
        (self.root/'library-seed/bank-assets/question.png').write_bytes(b'bad')
        with self.child('--prepare-desktop') as (p,events):
            error,_=self.until(events,'error');self.assertEqual(error['error']['code'],'seed_hash_mismatch');self.assertEqual(p.wait(timeout=10),11)

    def test_control_rejects_wrong_nonce_and_accepts_shutdown_or_eof(self):
        for content in ('',json.dumps(dict(protocol=PROTOCOL,command='shutdown',nonce='a'*64))+'\n'):
            control=ParentControl(io.StringIO(content),'a'*64);control.read();self.assertTrue(control.stop.is_set())
        class Stream:
            def __init__(self):self.lines=iter(['{"nonce":"bad"}\n',json.dumps(dict(protocol=PROTOCOL,command='shutdown',nonce='a'*64))+'\n'])
            def readline(self,n):return next(self.lines,'')
        control=ParentControl(Stream(),'a'*64);control.read();self.assertTrue(control.stop.is_set())

    def test_nonce_ownership_does_not_remove_other_launch(self):
        from app.hosting import clear_address
        self.base.joinpath('server.json').write_text(json.dumps(dict(pid=123,nonce='other')),encoding='utf8')
        clear_address(self.base,123,'ours');self.assertTrue((self.base/'server.json').exists())
        clear_address(self.base,123,'other');self.assertFalse((self.base/'server.json').exists())

    def test_half_initialized_server_fails_with_json_and_releases_databases(self):
        with self.child('--prepare-desktop') as (p,events):self.until(events,'prepared');self.assertEqual(p.wait(timeout=10),0)
        self.bootstrap="from app.services.knowledge_links import KnowledgeLinksService;KnowledgeLinksService.prepare_index=lambda s:(_ for _ in ()).throw(RuntimeError('synthetic startup error'));"
        with self.child('--desktop') as (p,events):
            error,_=self.until(events,'error');self.assertEqual(error['error']['code'],'initialization_failed');self.assertEqual(p.wait(timeout=10),20)
        self.assertFalse((Path(self.args.data_dir)/'server.json').exists())
        db=Path(self.args.library_dir)/'library.db';tmp=db.with_suffix('.move');db.rename(tmp);tmp.rename(db)

    @unittest.skipUnless(os.name=='nt','Windows process-handle verification')
    def test_parent_process_death_closes_pipe_and_sidecar_exits(self):
        self.parent_death()

    @unittest.skipUnless(os.name=='nt','Windows process-handle verification')
    def test_parent_process_death_with_closed_stdout_pipe_exits(self):
        self.parent_death(stdout_pipe=True)

    def parent_death(self,stdout_pipe=False):
        with self.child('--prepare-desktop') as (p,events):self.until(events,'prepared');self.assertEqual(p.wait(timeout=10),0)
        marker=self.base/'parent-ready.json';log=self.base/'orphan-test.stdout';address=Path(self.args.data_dir)/'server.json';trigger=self.base/'die-now'
        code='''import json,os,subprocess,time
from pathlib import Path
with open(LOG,'w',encoding='utf8') as out:
 child=subprocess.Popen(COMMAND,stdin=subprocess.PIPE,stdout=subprocess.PIPE if PIPE else out,stderr=out,env=ENV,cwd=CWD)
 end=time.monotonic()+40
 while not Path(ADDRESS).exists():
  if child.poll() is not None or time.monotonic()>end:raise RuntimeError('No address')
  time.sleep(.02)
 Path(MARKER).write_text(Path(ADDRESS).read_text(encoding='utf8'),encoding='utf8')
 while not Path(TRIGGER).exists():time.sleep(.02)
 os._exit(0)
'''
        preamble='\n'.join(k+'='+repr(v) for k,v in dict(LOG=str(log),COMMAND=self.command('--desktop'),ENV=self.env,CWD=str(self.base),ADDRESS=str(address),MARKER=str(marker),TRIGGER=str(trigger),PIPE=stdout_pipe).items())
        parent=subprocess.Popen([sys._base_executable,'-X','utf8','-c',preamble+'\n'+code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8')
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
        handle=None
        try:
            end=time.monotonic()+45
            while not marker.exists() and parent.poll() is None and time.monotonic()<end:time.sleep(.02)
            self.assertTrue(marker.exists())
            pid=json.loads(marker.read_text(encoding='utf8'))['pid']
            handle=kernel.OpenProcess(0x00100001,False,pid)  # SYNCHRONIZE | TERMINATE, own child only.
            if not handle:raise ctypes.WinError(ctypes.get_last_error())
            trigger.touch();out,err=parent.communicate(timeout=10);self.assertEqual(parent.returncode,0,err)
            self.assertEqual(kernel.WaitForSingleObject(handle,12000),0,'actual sidecar still alive after parent death')
        finally:
            if parent.poll() is None:parent.kill();parent.communicate(timeout=5)
            if handle:
                if kernel.WaitForSingleObject(handle,0)!=0:kernel.TerminateProcess(handle,1);kernel.WaitForSingleObject(handle,5000)
                kernel.CloseHandle(handle)
        end=time.monotonic()+12
        while address.exists() and time.monotonic()<end:time.sleep(.02)
        self.assertFalse(address.exists())
        if not stdout_pipe:
            while '"event": "stopped"' not in log.read_text(encoding='utf8') and time.monotonic()<end:time.sleep(.02)
            self.assertIn('"event": "stopped"',log.read_text(encoding='utf8'))

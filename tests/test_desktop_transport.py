import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app.agent.transport import CodexProcess,codex_executable
from app.agent.errors import AgentUnavailable


class DesktopTransportTests(unittest.TestCase):
    def test_locator_order_and_missing_explicit_path_never_silently_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);chosen=base/'chosen.exe';chosen.touch()
            known=base/'Programs/OpenAI/Codex/bin/codex.exe';known.parent.mkdir(parents=True);known.touch()
            with patch.dict(os.environ,dict(MATHLENS_CODEX_BIN=str(chosen),LOCALAPPDATA=str(base))),patch('app.agent.transport.shutil.which',return_value=None):
                self.assertEqual(codex_executable(),str(chosen));chosen.unlink();self.assertIsNone(codex_executable())
                os.environ.pop('MATHLENS_CODEX_BIN');self.assertEqual(codex_executable(),str(known))
                with patch('app.agent.transport.shutil.which',return_value='path.exe'):self.assertEqual(codex_executable(),'path.exe')
    def test_found_but_unlaunchable_is_not_not_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.agent.transport.codex_executable',return_value='found.exe'),patch('app.agent.transport.subprocess.Popen',side_effect=OSError('synthetic invalid executable')):
                with self.assertRaises(AgentUnavailable) as caught:CodexProcess(Path(folder),Path(folder),lambda x:None,lambda x:None)
            self.assertEqual(caught.exception.reason,'other');self.assertIn('已找到',str(caught.exception))
            self.assertFalse((Path(folder)/'codex.stderr.log').exists())

    def test_real_fake_server_drains_and_rotates_stderr_without_blocking_rpc(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'app-server').write_text('''import json,sys
for line in sys.stdin:
 value=json.loads(line)
 sys.stderr.write(('synthetic diagnostic x'*40+'\\n')*10000);sys.stderr.flush()
 print(json.dumps({'id':value['id'],'result':{'ok':True}}),flush=True)
''',encoding='utf8')
            with patch('app.agent.transport.codex_executable',return_value=sys._base_executable):
                process=CodexProcess(root,root,lambda x:None,lambda x:None)
                try:self.assertTrue(process.request('initialize',{},timeout=10)['ok'])
                finally:process.close()
            self.assertFalse(process.reader.is_alive());self.assertFalse(process.stderr_reader.is_alive())
            files=list(root.glob('codex.stderr.log*'));self.assertGreaterEqual(len(files),2);self.assertLessEqual(len(files),3)
            self.assertTrue(all(p.stat().st_size<=5*1024*1024 for p in files))
            for path in files:path.unlink()

    @unittest.skipUnless(os.name=='nt','Windows cmd experiment')
    def test_actual_cmd_direct_popen_result_is_explicit(self):
        with tempfile.TemporaryDirectory(prefix='cmd 空格 &!% ') as folder:
            path=Path(folder)/'codex.cmd';path.write_bytes(b'@echo off\r\n@echo synthetic-cmd-smoke\r\n')
            try:
                p=subprocess.Popen([str(path),'--version'],shell=False,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            except OSError as exc:
                print('cmd direct Popen: unsupported, winerror='+str(getattr(exc,'winerror',None)))
                with patch('app.agent.transport.codex_executable',return_value=str(path)):
                    with self.assertRaises(AgentUnavailable) as caught:CodexProcess(Path(folder),Path(folder),lambda x:None,lambda x:None)
                self.assertEqual(caught.exception.reason,'other')
            else:
                out,err=p.communicate(timeout=5);self.assertEqual(p.returncode,0,err);self.assertIn(b'synthetic-cmd-smoke',out)
                print('cmd direct Popen: controlled batch launch supported; npm protocol remains unverified')
            with patch('app.agent.transport.codex_executable',return_value=str(path)):
                with self.assertRaises(AgentUnavailable) as caught:CodexProcess(Path(folder),Path(folder),lambda x:None,lambda x:None)
            self.assertEqual(caught.exception.reason,'other')

    @unittest.skipUnless(os.name=='nt','Windows cmd expansion experiment')
    def test_cmd_percent_path_is_not_reliable_even_with_shell_false(self):
        with tempfile.TemporaryDirectory(prefix='cmd %MATHLENS_CMD_SMOKE% ') as folder:
            path=Path(folder)/'codex.cmd';path.write_bytes(b'@echo off\r\n@echo synthetic-cmd-percent\r\n')
            env=dict(os.environ,MATHLENS_CMD_SMOKE='expanded-to-another-directory')
            try:
                p=subprocess.Popen([str(path),'--version'],shell=False,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                out,err=p.communicate(timeout=5)
                print('cmd percent-path direct Popen: returncode='+str(p.returncode)+', expected-marker='+str(b'synthetic-cmd-percent' in out))
                self.assertNotIn(b'synthetic-cmd-percent',out)
            except OSError as exc:print('cmd percent-path direct Popen: winerror='+str(getattr(exc,'winerror',None)))

#!/usr/bin/env python3
"""Local mocked checks only: never calls Docker, the API or candidate code."""
import ast
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
exam = types.ModuleType('private_exam')
exec(compile((ROOT/'code-exam-private.py').read_text(), str(ROOT/'code-exam-private.py'), 'exec'), exam.__dict__)
IMAGE='sha256:'+'a'*64

class FakeProcess:
    returncode = 0
    def __init__(self, cmd, stdin, stdout, stderr, env):
        self.cmd=cmd; self.env=env; self.source=stdin.read()
        marker=re.search(rb'EXAM_DONE_[0-9a-f]+',self.source).group(0)
        stdout.write(marker+b'\n'); stdout.flush()
    def poll(self): return self.returncode
    def kill(self): self.returncode=-9
    def wait(self, timeout): return self.returncode

class ExamTests(unittest.TestCase):
    def test_upstream_tasks_are_unchanged(self):
        module=ast.parse((ROOT/'upstream/scripts/code-exam.py').read_text())
        assignment=next(n for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='P' for t in n.targets))
        self.assertEqual(exam.P,ast.literal_eval(assignment.value))
        self.assertEqual(len(exam.P),12)

    def test_restrictions_stdin_and_clean_environment(self):
        seen=[]
        def factory(*args,**kwargs):
            process=FakeProcess(*args,**kwargs); seen.append(process); return process
        with patch.object(exam.subprocess,'Popen',side_effect=factory), patch.object(exam.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stderr=b'')) as cleanup:
            ok,error,meta=exam.execute_candidate("def f(): return 1", "assert f()==1",IMAGE)
        self.assertTrue(ok,error)
        cmd=seen[0].cmd
        for flag in ('--pull=never','--runtime=runc','--network=none','--read-only','--user=65534:65534','--cap-drop=ALL','--security-opt=no-new-privileges','--memory=256m','--memory-swap=256m','--cpus=1','--pids-limit=32'):
            self.assertIn(flag,cmd)
        self.assertFalse(any(x.startswith(('--mount','--volume','--gpus','--device')) or x in ('-v','-e') for x in cmd))
        self.assertNotIn('Authorization',str(seen[0].env))
        self.assertIn(b'assert f()==1',seen[0].source)
        self.assertEqual(cmd[-1],'-')
        self.assertEqual(cleanup.call_args.args[0][-3:-1],['rm','-f'])

    def test_done_marker_does_not_override_nonzero_exit(self):
        class Failed(FakeProcess): returncode=1
        with patch.object(exam.subprocess,'Popen',Failed), patch.object(exam.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stderr=b'')):
            ok,error,_=exam.execute_candidate("print('DONE')", "assert False",IMAGE)
        self.assertFalse(ok); self.assertIn('exited1',error)

    def test_timeout_forces_owned_container_removal(self):
        processes=[]
        class Hanging(FakeProcess):
            returncode=None
            def __init__(self,*a,**kw): super().__init__(*a,**kw); processes.append(self)
        with patch.object(exam.subprocess,'Popen',Hanging), patch.object(exam.time,'monotonic',side_effect=[0,26,27]), patch.object(exam.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stderr=b'')) as cleanup:
            ok,error,metadata=exam.execute_candidate('while True: pass','assert True',IMAGE)
        self.assertFalse(ok); self.assertEqual(error,'timeout25s')
        self.assertEqual(processes[0].returncode,-9)
        self.assertEqual(cleanup.call_args.args[0][-1],metadata['container_name'])

    def test_failed_cleanup_fails_successful_candidate(self):
        with patch.object(exam.subprocess,'Popen',FakeProcess), patch.object(exam.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stderr=b'daemon unavailable')):
            ok,error,_=exam.execute_candidate('pass','assert True',IMAGE)
        self.assertFalse(ok); self.assertIn('cleanup failed',error)

    def test_absent_image_never_pulls(self):
        with patch.object(exam.subprocess,'run',return_value=types.SimpleNamespace(returncode=1)) as invoke:
            with self.assertRaises(RuntimeError): exam.checked_image(exam.DEFAULT_IMAGE)
        self.assertEqual(invoke.call_count,1)
        self.assertIn('inspect',invoke.call_args.args[0]); self.assertNotIn('pull',invoke.call_args.args[0])

    def test_bearer_auth_and_actual_usage_retained(self):
        payload={'choices':[{'message':{'content':'def f(): return 1'},'finish_reason':'stop'}], 'usage':{'prompt_tokens':51,'completion_tokens':7,'total_tokens':58,'completion_tokens_details':{'reasoning_tokens':3}}}
        class Opener:
            def open(self,request,timeout):
                self.request=request
                self.body=json.loads(request.data)
                return io.StringIO(json.dumps(payload))
        opener=Opener()
        with tempfile.TemporaryDirectory() as temp:
            key=Path(temp)/'key'; key.write_text('private-test-token')
            with patch.object(exam.urllib.request,'build_opener',return_value=opener):
                client=exam.ModelClient('http://127.0.0.1:8888',key)
            _,metadata=client.ask(exam.P[0][1])
        self.assertEqual(opener.request.get_header('Authorization'),'Bearer private-test-token')
        self.assertEqual(opener.body['max_tokens'],1600)
        self.assertEqual(opener.body['chat_template_kwargs'],{'enable_thinking':True,'reasoning_effort':'low'})
        self.assertEqual(metadata['usage'],payload['usage'])
        self.assertNotIn('private-test-token',str(metadata))

    def test_full_count_failures_and_missing_usage_not_imputed(self):
        class Client:
            count=0
            def ask(self,prompt):
                self.count+=1
                if self.count==1: raise RuntimeError('sensitive detail must not be printed')
                return 'pass',{'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}
        with patch.object(exam,'execute_candidate',return_value=(False,'assertion failed',{})),contextlib.redirect_stdout(io.StringIO()) as output:
            result=exam.run_exam(Client(),IMAGE,1)
        self.assertEqual(result['total'],12); self.assertEqual(result['passed'],0)
        self.assertEqual(len(result['attempts']),12)
        self.assertEqual(result['usage_totals']['prompt_tokens'],{'sum_reported':110,'attempts_reporting':11})
        self.assertNotIn('sensitive detail',output.getvalue())
        args=types.SimpleNamespace(out=None,sandbox_image=IMAGE,base='http://127.0.0.1:8888',api_key_file='unused',repeats=1)
        with patch.object(exam,'parse_args',return_value=args),patch.object(exam,'checked_image',return_value=IMAGE),patch.object(exam,'ModelClient'),patch.object(exam,'run_exam',return_value=result),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(exam.main([]),1)

if __name__=='__main__': unittest.main()

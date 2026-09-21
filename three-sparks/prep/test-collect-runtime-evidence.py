#!/usr/bin/env python3
"""Offline fixture/fail-closed checks; never runs Docker, SSH, API or GPU calls."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
_HAVE_LOGS=(HERE/'evidence/rank0/startup-fair-v2.log').exists()
_WHY='needs the private full startup logs (not redistributed); passes on the operator copy'
spec=importlib.util.spec_from_file_location('collector',HERE/'collect-runtime-evidence.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class EvidenceChecks(unittest.TestCase):
    @unittest.skipUnless(_HAVE_LOGS,_WHY)
    def test_actual_saved_startup(self):
        for name,pool,blocks,budget,total in [('startup-v1.log',7101928,2578,2048,363),('startup-fair-v2.log',7021917,2563,2304,365)]:
            r=m.parse_logs((HERE/'evidence/rank0'/name).read_text())
            self.assertEqual(r['reported_gpu_kv_cache_tokens'],[pool])
            self.assertEqual(r['observed_num_gpu_blocks'],[blocks])
            self.assertEqual(r['settings']['max_model_len'],[1000000])
            self.assertEqual(r['settings']['max_num_scheduled_tokens'],[budget])
            self.assertEqual(sum(g['blocks_per_request'] for g in r['observed_cache_groups']),total)
            self.assertEqual(r['effective_attention_block_tokens'],[3328])
            self.assertEqual(r['effective_draft_kv_dtype_override'],['fp8'])
    def test_secret_filter_and_duplicate_flags(self):
        f=m.sanitized_flags(['vllm','serve','--api-key','NOT_FOR_OUTPUT','--max-num-batched-tokens','2048','--max-num-batched-tokens','2304','--speculative-config','{"method":"dflash","num_speculative_tokens":7,"api_key":"NOT_FOR_OUTPUT"}'])
        self.assertNotIn('NOT_FOR_OUTPUT',json.dumps(f))
        self.assertEqual(f['max-num-batched-tokens'],[2048,2304])
        self.assertEqual(f['speculative-config'][-1],{'method':'dflash','num_speculative_tokens':7})
    @unittest.skipUnless(_HAVE_LOGS,_WHY)
    def test_configuration_guard_and_offload_rejection(self):
        argv=['/usr/local/bin/vllm','serve','/model','--node-rank','0','--tensor-parallel-size','3','--pipeline-parallel-size','1','--nnodes','3','--max-num-seqs','8','--max-model-len','1000000','--max-num-batched-tokens','2304','--long-prefill-token-threshold','256','--enable-expert-parallel','--enable-chunked-prefill','--enforce-eager','--quantization','exl3','--kv-cache-dtype','fp8','--speculative-config','{"method":"dflash","num_speculative_tokens":7}','--limit-mm-per-prompt','{"image":4,"video":0}','--hf-overrides','{"index_topk":8192}']
        installed={'pid1_argv':argv,'vllm_version':'0.1.dev20051+g487ecf187','files':{n:{'sha256':'fixture'} for n in ('config/cache.py','config/offload.py','config/scheduler.py','config/vllm.py','v1/core/sched/scheduler.py')},'defaults':{k:{'value':v} for k,v in {'cpu_offload_gb':0,'offload_group_size':0,'offload_backend':'auto','kv_offloading_size':None,'disable_chunked_mm_input':False}.items()}}
        inspection={'Id':'fixture-container','Image':m.IMAGE,'State':{'Running':True,'StartedAt':'fixture-start'},'Config':{'Env':['PRIVATE_TEST_SECRET=NOT_FOR_OUTPUT','HAREM_EXL3_FULLSCOPE=1','HAREM_DRAFT_KV_DTYPE=fp8']}}
        def fake_command(command,input_text=None):
            return json.dumps(installed if command[1]=='exec' else [inspection])
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'prep').mkdir()
            (root/'prep/source-pins.json').write_text((HERE/'source-pins.json').read_text())
            for index,extra in enumerate(([],['--cpu-offload-gb','1'])):
                installed['pid1_argv']=argv+extra
                output=root/f'evidence-{index}.json'
                cli=['collect-runtime-evidence.py','--root',str(root),'--container','fixture','--output',str(output),'--startup-log',str(HERE/'evidence/rank0/startup-fair-v2.log')]
                with patch.object(m,'command',fake_command),patch('sys.argv',cli),contextlib.redirect_stdout(io.StringIO()):
                    rc=m.main()
                result=json.loads(output.read_text())
                self.assertEqual(rc,0 if index==0 else 2,result['checks'])
                self.assertEqual(result['ready_for_reviewed_long_test'],index==0)
                self.assertNotIn('NOT_FOR_OUTPUT',output.read_text())
                self.assertEqual(output.stat().st_mode&0o777,0o600)

if __name__=='__main__':unittest.main()

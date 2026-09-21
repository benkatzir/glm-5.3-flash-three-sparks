#!/usr/bin/env python3
"""Read-only, head-local GLM launch evidence. Never contacts the model API/GPU.

Docker inspect/logs and a stdlib-only reader in the existing container are used.
Only allowlisted values are emitted; full argv, env, logs and key contents are not.
Exit 0 means this evidence matches the requested *configuration*, not that C8 long
context, broad accuracy, or speed has passed. Output must be a fresh private file.
"""
import argparse
import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

IMAGE = 'sha256:af1cd7490e0bd7f47c3ede8752e87625f3e080a4f5224d9191ca455aa56cdfbb'
FLAGS = {
    'tensor-parallel-size', 'pipeline-parallel-size', 'nnodes', 'node-rank',
    'max-model-len', 'max-num-seqs', 'max-num-batched-tokens',
    'max-num-scheduled-tokens', 'long-prefill-token-threshold',
    'gpu-memory-utilization', 'kv-cache-dtype', 'block-size', 'mamba-cache-mode',
    'cpu-offload-gb', 'kv-offloading-size', 'kv-offloading-backend',
    'offload-group-size', 'offload-backend', 'swap-space',
    'quantization', 'attention-backend', 'dtype', 'served-model-name', 'port',
    'enable-expert-parallel', 'enable-chunked-prefill', 'enable-prefix-caching',
    'disable-chunked-mm-input', 'no-disable-chunked-mm-input',
    'language-model-only', 'enforce-eager', 'headless', 'async-scheduling',
    'speculative-config', 'limit-mm-per-prompt', 'mm-processor-kwargs', 'hf-overrides',
}
BOOL_FLAGS = {
    'enable-expert-parallel', 'enable-chunked-prefill', 'enable-prefix-caching',
    'disable-chunked-mm-input', 'no-disable-chunked-mm-input',
    'language-model-only', 'enforce-eager', 'headless', 'async-scheduling',
}
JSON_FLAGS = {'speculative-config', 'limit-mm-per-prompt', 'mm-processor-kwargs', 'hf-overrides'}
JSON_KEYS = {
    'speculative-config': {'method', 'num_speculative_tokens', 'model', 'draft_tensor_parallel_size', 'max_model_len', 'draft_model_config', 'draft_model_config_overrides', 'kv_cache_dtype'},
    'limit-mm-per-prompt': {'image', 'video'},
    'mm-processor-kwargs': {'max_image_tokens', 'min_image_tokens', 'max_pixels'},
    'hf-overrides': {'index_topk', 'quantization_config_file'},
}
LOG_FIELDS = {
    'tensor_parallel_size', 'pipeline_parallel_size', 'max_model_len', 'max_seq_len',
    'max_num_seqs', 'max_num_batched_tokens', 'max_num_scheduled_tokens',
    'long_prefill_token_threshold', 'gpu_memory_utilization', 'block_size',
    'mamba_cache_mode', 'cache_dtype', 'kv_cache_dtype', 'cpu_offload_gb',
    'kv_offloading_size', 'offload_group_size', 'offload_backend',
    'disable_chunked_mm_input', 'enable_expert_parallel',
}
ENV_KEYS = {
    'NODE_RANK', 'TP_SIZE', 'ENABLE_EP', 'NCCL_NET', 'NCCL_NET_PLUGIN',
    'NCCL_IB_DISABLE', 'NCCL_ALGO', 'NCCL_PROTO', 'CUDA_EXL3_MLA_TUNE_VERBOSE',
    'CUDA_EXL3_DEBUG_NAMES', 'HAREM_GLM47_INDEX_TOPK', 'HAREM_KDA_FLASHKDA',
    'HAREM_GLM47_FAILCLOSED', 'HAREM_XGRAMMAR_BACKPORT',
    'HAREM_DRAFT_KV_DTYPE', 'HAREM_SW_BLOCK_SIZE', 'HAREM_VISION',
    'HAREM_EXL3_FULLSCOPE', 'HAREM_INDEXER_WS_MODE', 'HAREM_PREFIX_HIT',
    'HAREM_KPOOL_TAIL_FIX', 'HAREM_DISABLE_PERSISTENT_TOPK',
    'HAREM_SM12_ITEMS', 'HAREM_FASTLOAD_MODE',
}
DEFAULT_FIELDS = {'cpu_offload_gb', 'offload_group_size', 'offload_backend',
                  'kv_offloading_size', 'kv_offloading_backend',
                  'disable_chunked_mm_input', 'long_prefill_token_threshold'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def scalar(text):
    if text in ('null', 'true', 'false'):
        return {'null': None, 'true': True, 'false': False}[text]
    if re.fullmatch(r'[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?', text):
        text = text.replace(',', '')
    try:
        v = ast.literal_eval(text)
        return v if v is None or type(v) in (str, bool, int, float) else None
    except (ValueError, SyntaxError):
        return text


def sanitized_flags(argv):
    out = {}
    for i, arg in enumerate(argv):
        if not arg.startswith('--'):
            continue
        name, sep, raw = arg[2:].partition('=')
        if name not in FLAGS:
            continue
        if not sep:
            raw = True if name in BOOL_FLAGS else (argv[i+1] if i+1 < len(argv) and not argv[i+1].startswith('--') else None)
        if name in JSON_FLAGS:
            try:
                obj = json.loads(raw)
                # Nested free-form values are deliberately not copied.
                value = {k: v for k, v in obj.items() if k in JSON_KEYS[name] and (v is None or type(v) in (str, int, float, bool))}
            except (ValueError, TypeError, AttributeError):
                value = {'parse_error': True}
        else:
            value = scalar(raw) if isinstance(raw, str) else raw
        out.setdefault(name, []).append(value)
    return out


# Executed only with stdlib; no vLLM/torch import, GPU query, API call or file write.
READER = r'''
import ast, hashlib, importlib.metadata, json, os, pathlib, site
fields = {'cpu_offload_gb','offload_group_size','offload_backend','kv_offloading_size','kv_offloading_backend','disable_chunked_mm_input','long_prefill_token_threshold'}
roots = [pathlib.Path(p)/'vllm' for p in site.getsitepackages()]
root = next((p for p in roots if (p/'config/scheduler.py').is_file()), None)
result = {'files': {}, 'defaults': {}}
if root:
 for rel in ['config/cache.py','config/offload.py','config/scheduler.py','config/vllm.py','config/speculative.py','v1/core/sched/scheduler.py','v1/core/encoder_cache_manager.py','v1/kv_cache_interface.py']:
  p=root/rel
  if not p.is_file(): continue
  text=p.read_text()
  result['files'][rel]={'sha256':hashlib.sha256(text.encode()).hexdigest(),'bytes':len(text.encode())}
  if rel not in ('config/cache.py','config/offload.py','config/scheduler.py'): continue
  for n in ast.walk(ast.parse(text)):
   if not isinstance(n,ast.AnnAssign) or not isinstance(n.target,ast.Name) or n.target.id not in fields: continue
   value=n.value
   if isinstance(value,ast.Call): value=next((k.value for k in value.keywords if k.arg=='default'),None)
   try: parsed=ast.literal_eval(value)
   except Exception: continue
   result['defaults'][n.target.id]={'value':parsed,'source':rel,'line':n.lineno}
try:result['vllm_version']=importlib.metadata.version('vllm')
except importlib.metadata.PackageNotFoundError:result['vllm_version']=None
result['pid1_argv']=pathlib.Path('/proc/1/cmdline').read_bytes().decode().strip('\0').split('\0')
print(json.dumps(result))
'''


def command(argv, input_text=None):
    try:
        done = subprocess.run(argv, input=input_text, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Read-only subprocess failed: '+type(exc).__name__) from None
    if done.returncode:
        raise RuntimeError('Read-only subprocess returned exit '+str(done.returncode))
    return done.stdout


def parse_logs(text):
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    fields = {}
    for key in sorted(LOG_FIELDS):
        # Accept config repr and Python/JSON dictionary output, never whole lines.
        pattern = r'(?<![A-Za-z0-9_])' + re.escape(key) + r'''["']?\s*[:=]\s*(None|null|True|False|true|false|[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?|["'][A-Za-z0-9_./-]+["'])'''
        values = [scalar(v) for v in re.findall(pattern, text)]
        if values:
            fields[key] = list(dict.fromkeys(values))
    scheduled = re.findall(r'max_num_scheduled_tokens is set to\s*(\d+)', text)
    if scheduled:
        fields.setdefault('max_num_scheduled_tokens', [])
        for value in map(int, scheduled):
            if value not in fields['max_num_scheduled_tokens']: fields['max_num_scheduled_tokens'].append(value)
    pools = [int(s.replace(',', '')) for s in re.findall(r'GPU KV cache size:\s*([\d,]+)\s*tokens', text)]
    gpu_gib = [float(s) for s in re.findall(r'Available KV cache memory:\s*([\d.]+)\s*GiB', text)]
    concurrency = [{'request_tokens': int(n.replace(',', '')), 'reported_concurrency': float(c)}
                   for n, c in re.findall(r'Maximum concurrency for\s*([\d,]+)\s*tokens per request:\s*([\d.]+)x', text)]
    blocks = [int(s) for s in re.findall(r'\bnum_gpu_blocks[\s=:]+(\d+)', text)]
    breakdowns = [{'num_blocks': int(n.replace(',', '')), 'blocks_per_request': int(b.replace(',', '')), 'max_model_len': int(c.replace(',', ''))}
                  for n,b,c in re.findall(r'HAREM-TP3 KV pool breakdown:\s*num_blocks=([\d,]+),\s*blocks/request=([\d,]+),\s*max_model_len=([\d,]+)',text)]
    blocks.extend(item['num_blocks'] for item in breakdowns)
    groups = [{'spec': spec, 'layers': int(layers), 'page_bytes': int(page.replace(',', '')), 'bytes_per_block': int(size.replace(',', '')),
               'max_bytes_per_request': int(req.replace(',', '')), 'blocks_per_request': int(count.replace(',', ''))}
              for spec,layers,page,size,req,count in re.findall(r'\b([A-Za-z0-9]+Spec):\s*(\d+) layer\(s\), page ([\d,]+) B, bytes/block ([\d,]+) B, max/req ([\d,]+) B -> ([\d,]+) block\(s\)',text)]
    attention_blocks = [int(s.replace(',', '')) for s in re.findall(r'Setting attention block size to\s*([\d,]+)\s*tokens',text)]
    draft_dtype = re.findall(r"draft kv_cache_dtype 'auto' -> '([A-Za-z0-9_]+)'",text)
    mamba_modes = re.findall(r"Mamba cache mode is set to '([A-Za-z0-9_]+)'",text)
    return {'settings': fields, 'reported_gpu_kv_cache_tokens': list(dict.fromkeys(pools)),
            'available_kv_cache_memory_gib': gpu_gib, 'reported_max_concurrency': concurrency,
            'observed_num_gpu_blocks': list(dict.fromkeys(blocks)),
            'observed_pool_breakdowns': breakdowns, 'observed_cache_groups': groups,
            'effective_attention_block_tokens':list(dict.fromkeys(attention_blocks)),
            'effective_draft_kv_dtype_override':list(dict.fromkeys(draft_dtype)),
            'effective_mamba_cache_mode':list(dict.fromkeys(mamba_modes)),
            'application_startup_complete_seen': 'Application startup complete' in text,
            'prelude_starting_vllm_seen': 'patches applied (tp3full arm); starting vllm serve' in text}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--container', required=True)
    p.add_argument('--root', type=Path, default=Path('/home/ben/glm53-lab'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--startup-log', type=Path, help='Optional retained log for this same container; provenance must be reviewed')
    p.add_argument('--expected-image', default=IMAGE)
    p.add_argument('--min-reported-pool-tokens', type=int, default=6000000,
                   help='Conservative evidence guard only, not a hybrid-cache allocation proof')
    a=p.parse_args()
    os.umask(0o077)
    if a.output.exists(): p.error('Output must not already exist')
    inspection=json.loads(command(['docker','container','inspect',a.container]))[0]
    container_id=inspection['Id']
    image_id=inspection['Image']
    state=inspection['State']
    install=json.loads(command(['docker','exec','-i',container_id,'python3','-'], READER))
    actual_argv=install.pop('pid1_argv')
    flags=sanitized_flags(actual_argv)
    env=dict(s.split('=',1) for s in inspection['Config'].get('Env',[]) if '=' in s)
    safe_env={k:env[k] for k in sorted(ENV_KEYS & env.keys())}
    suspicious_env=sorted(k for k in env if re.search(r'OFFLOAD|LMCACHE|KV_TRANSFER',k))
    if a.startup_log:
        log_bytes=a.startup_log.read_bytes(); log_origin='provided_retained_file'
    else:
        # Docker writes both stdout and stderr to logs. Capture both without emitting.
        proc=subprocess.run(['docker','logs','--timestamps',container_id],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
        if proc.returncode: raise RuntimeError('docker logs failed')
        log_bytes=proc.stdout+b'\n'+proc.stderr; log_origin='docker_logs_current_container'
    log=parse_logs(log_bytes.decode(errors='replace'))
    def effective(name, default=None):
        return flags.get(name,[default])[-1]
    def installed_default(name):
        return install.get('defaults',{}).get(name,{}).get('value', 'UNKNOWN')
    no_offload_values={
        'cpu_offload_gb':effective('cpu-offload-gb',installed_default('cpu_offload_gb')),
        'offload_group_size':effective('offload-group-size',installed_default('offload_group_size')),
        'kv_offloading_size':effective('kv-offloading-size',installed_default('kv_offloading_size')),
        'offload_backend':effective('offload-backend',installed_default('offload_backend')),
    }
    opaque_flags=[s.split('=',1)[0] for s in actual_argv if s.startswith(('--offload-config','--kv-transfer-config','--config','--load-config'))]
    no_offload=(no_offload_values['cpu_offload_gb']==0 and no_offload_values['offload_group_size']==0
                and no_offload_values['kv_offloading_size'] in (None,0)
                and no_offload_values['offload_backend']=='auto' and not suspicious_env and not opaque_flags)
    for key in ('cpu_offload_gb','offload_group_size','kv_offloading_size'):
        if any(v not in (0,None) for v in log['settings'].get(key,[])): no_offload=False
    sources={}
    for relative in ('prep/source-pins.json','prep/download-manifest.json','prep/start-private-tp3.sh',
                     'prep/private-entry.sh','prep/glm_private_auth.py','runtime/tp3-prelude.sh',
                     'overlay-v1/sparse_attn_indexer.py','overlay-v1/sparse_attn_indexer_kpool.py',
                     'nccl-mesh/libnccl-net-mesh.so','models/target-tp3/config.json','models/draft-tp3/config.json'):
        path=a.root/relative
        if path.is_file():
            body=path.read_bytes(); sources[relative]={'sha256':sha(body),'bytes':len(body)}
    pins_path=a.root/'prep/source-pins.json'
    pins=json.loads(pins_path.read_text()) if pins_path.is_file() else {}
    declared={k:pins[k] for k in ('recipe','cuda_exl3','base_image','target','draft','template','mesh_plugin_revision') if k in pins}
    scheduled=log['settings'].get('max_num_scheduled_tokens',[])
    pools=log['reported_gpu_kv_cache_tokens']
    checks={
        'container_running':bool(state.get('Running')),
        'expected_image':image_id==a.expected_image,
        'pid1_is_vllm_serve':any(Path(s).name=='vllm' for s in actual_argv) and 'serve' in actual_argv,
        'head_rank0':effective('node-rank')==0,
        'tp3_pp1_three_nodes':effective('tensor-parallel-size')==3 and effective('pipeline-parallel-size')==1 and effective('nnodes')==3,
        'expert_parallel':effective('enable-expert-parallel') is True,
        'max_sequences8':effective('max-num-seqs')==8,
        'model_context1000000':effective('max-model-len')==1000000,
        'batch2304':effective('max-num-batched-tokens')==2304,
        'threshold256':effective('long-prefill-token-threshold')==256,
        'scheduled2304_observed':scheduled==[2304],
        'chunked_prefill_enabled':effective('enable-chunked-prefill') is True,
        'chunked_mm_input_enabled':effective('disable-chunked-mm-input',installed_default('disable_chunked_mm_input')) is False,
        'native_image_input_enabled':not effective('language-model-only',False) and effective('limit-mm-per-prompt',{}).get('image',0)>0,
        'dflash7':effective('speculative-config',{}).get('method')=='dflash' and effective('speculative-config',{}).get('num_speculative_tokens')==7,
        'exl3_fp8_eager':effective('quantization')=='exl3' and effective('kv-cache-dtype')=='fp8' and effective('enforce-eager') is True,
        'fullscope_index8192_draft_fp8':effective('hf-overrides',{}).get('index_topk')==8192 and safe_env.get('HAREM_EXL3_FULLSCOPE')=='1' and safe_env.get('HAREM_DRAFT_KV_DTYPE')=='fp8',
        'observed_attention3328_mamba_align_draft_fp8':log['effective_attention_block_tokens']==[3328] and log['effective_mamba_cache_mode']==['align'] and log['effective_draft_kv_dtype_override']==['fp8'],
        'no_configured_weight_or_kv_offload':no_offload,
        'observed_pool_above_conservative_guard':bool(pools) and min(pools)>=a.min_reported_pool_tokens,
        'startup_complete_seen':log['application_startup_complete_seen'],
        'vllm_pinned_version': '487ecf187' in (install.get('vllm_version') or ''),
        'installed_scheduler_and_offload_source_hashes_present':all(k in install.get('files',{}) for k in ('config/cache.py','config/offload.py','config/scheduler.py','config/vllm.py','v1/core/sched/scheduler.py')),
        'declared_source_pins_present':all(k in declared for k in ('recipe','cuda_exl3','base_image','target','draft','mesh_plugin_revision')),
    }
    # Incompatible explicit log settings must not silently pass CLI checks.
    expected={'tensor_parallel_size':3,'pipeline_parallel_size':1,'max_model_len':1000000,
              'max_seq_len':1000000,'max_num_seqs':8,'max_num_batched_tokens':2304,'long_prefill_token_threshold':256}
    checks['no_conflicting_observed_config']=all(all(v==target for v in log['settings'].get(k,[])) for k,target in expected.items())
    again=json.loads(command(['docker','container','inspect',container_id]))[0]
    checks['same_running_container_at_end']=again['State'].get('Running') and again['State'].get('StartedAt')==state.get('StartedAt')
    result={
        'schema':'glm53.runtime-evidence.v1','collected_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'collector_sha256':sha(Path(__file__).read_bytes()),
        'scope':'Head-local launch/config/source evidence. No model API calls, GPU tests, process mutation, or claim of successful C8 long-context inference.',
        'container':{'id':container_id,'image_id':image_id,'started_at':state.get('StartedAt'),'pid1_flags':flags,'selected_environment':safe_env},
        'observed_startup':log,'startup_evidence':{'origin':log_origin,'sha256':sha(log_bytes),'bytes':len(log_bytes),
            'path':str(a.startup_log) if a.startup_log else None,'container_id':container_id},
        'installed_sources_and_defaults':install,'host_file_identities':sources,'declared_source_pins':declared,
        'no_offload_evidence':{'resolved_values':no_offload_values,'basis':'Current PID1 args plus installed source defaults and any observed config fields; integrated Spark system memory is not claimed to be discrete VRAM.',
            'unreviewed_offload_environment_names':suspicious_env,'opaque_configuration_flags':opaque_flags},
        'capacity':{'reported_pool_guard_tokens':a.min_reported_pool_tokens,'actual_cache_block_count':log['observed_num_gpu_blocks'] or None,
            'allocation_proof':False,'note':'Reported pool and concurrency come from startup. Do not substitute the v1 pool or infer actual blocks here. Hybrid groups make tokens/3328 an invalid block-count derivation. Actual 8×500k residency is evaluated by the long client with telemetry.'},
        'checks':checks,'ready_for_reviewed_long_test':all(checks.values()),
        'general_or_native_relative_accuracy_claimed':False,
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps({'output':str(a.output),'sha256':sha(a.output.read_bytes()),'ready_for_reviewed_long_test':result['ready_for_reviewed_long_test'],
                      'observed_pool_tokens':pools,'failed_checks':[k for k,v in checks.items() if not v]}))
    return 0 if result['ready_for_reviewed_long_test'] else 2


if __name__=='__main__':
    try:sys.exit(main())
    except (RuntimeError,subprocess.TimeoutExpired) as exc:
        print(json.dumps({'collection_failed':True,'error_type':type(exc).__name__}),file=sys.stderr);sys.exit(1)

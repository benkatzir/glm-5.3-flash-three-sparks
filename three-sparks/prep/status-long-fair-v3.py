#!/usr/bin/env python3
"""Read private, existing qualification telemetry; never call the model API."""
import json
from pathlib import Path

base = Path('/home/ben/glm53-lab/longvision-c8-v1')
run = base / 'runs/fair-v3'

def rows(path):
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # A writer may not have flushed its last line yet.
    return result

metrics = rows(run / 'metrics.jsonl')
guard = rows(base / 'memory-guard-fair-v3/guard.jsonl')
samples = [r for r in guard if r.get('event') == 'memory_sample']
out = {'elapsed_s': round((metrics[-1]['end_ns'] - metrics[0]['start_ns']) / 1e9, 1) if metrics else None}
if metrics:
    out['latest_metrics'] = {k.removeprefix('vllm:'): [v['value'] for v in vs]
                             for k, vs in metrics[-1].get('values', {}).items()}
    out['metric_read_errors'] = sum('error_type' in row for row in metrics)
if samples:
    out['memory_latest_gib'] = {r['node']: round(r['mem_available_gib'], 2)
                                for r in samples[-1]['readings'] if 'mem_available_gib' in r}
    out['memory_minimum_gib'] = {node: round(min(r['mem_available_gib'] for s in samples
                                              for r in s['readings'] if r['node'] == node
                                              and 'mem_available_gib' in r), 2)
                                for node in ('head', 'worker1', 'worker2')}
    out['memory_guard_polls'] = len(samples)
out['guard_triggered'] = any(r.get('event') == 'client_stop_trigger' for r in guard)
out['generated_tokens_so_far'] = []
for index in range(8):
    events = rows(run / f'case-{index:02d}' / 'events.jsonl')
    out['generated_tokens_so_far'].append(events[-1].get('token_ids_count', 0) if events else 0)
out['finished_result_files'] = len(list(run.glob('case-*/result.json')))
out['summary_exists'] = (run / 'summary.json').exists()
print(json.dumps(out, indent=2))

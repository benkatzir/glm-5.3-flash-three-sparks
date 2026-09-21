# Current GLM runtime evidence collector

Prepared locally; no SSH, API calls, GPU work, or serving changes were made. The
collector reads Docker inspect/logs and starts a stdlib-only Python file reader in
the **existing head container**. It does not import torch/vLLM or read the API key.
It writes one new private JSON artifact. It never prints full argv, environment,
startup logs, or secrets; only explicit allowlisted fields and source hashes remain.

Copy `collect-runtime-evidence.py` into `/home/ben/glm53-lab/prep/`, then after the
fair-v2 container is healthy run on the head, substituting its exact container name:

```bash
python3 /home/ben/glm53-lab/prep/collect-runtime-evidence.py \
  --container ACTUAL_FAIR_V2_HEAD_CONTAINER \
  --root /home/ben/glm53-lab \
  --output /home/ben/glm53-lab/private/runtime-evidence-fair-v2.json
```

The file must be fresh. Exit0 means observed launch evidence matches the reviewed
profile; exit2 writes the evidence plus failed checks for review. Exit1 indicates
collection failed. The default image expectation is the actually built immutable
`sha256:af1cd7490e0bd7f47c3ede8752e87625f3e080a4f5224d9191ca455aa56cdfbb`.
This is a configuration/evidence guard, not a model-quality or C8-residency pass.

Checks include current PID1 vLLM argv; TP3/PP1/three configured nodes/head rank0;
EP; max sequences8; context1,000,000; batch2304/threshold256; observed scheduled
budget2304; chunked prefill/MM; image input; EXL3/fullscope/index8192; DFlash7 with
observed FP8 draft override; FP8 target KV; eager mode; observed attention block
3328/Mamba align; startup completion; current container image/version and source
hashes. It resolves CPU-weight and KV-offload controls from current args and
installed source defaults and rejects unknown offload environment/config paths.
Source pins are recorded as **declared build/checkpoint provenance**; the stale
historical `runtime_status` in source-pins.json is neither copied nor changed.

The default guard requires an observed startup pool of at least6,000,000 tokens.
That guard gives headroom; it is not a general hybrid-cache allocation formula.
Exact available blocks/group sizes are recorded from the patched pool-breakdown
log when present. No reported pool or actual block count is invented. Missing
actual block evidence stays null. Neither tokens/3328 nor nominal128GiB×3 is used
to infer blocks. This head-only collector does not independently certify worker
images/configs, physical page residency or absence of OS paging; retain the
existing per-rank provenance and actual long-test telemetry as separate evidence.

Use current Docker logs by default. If startup has already rotated out, optional
`--startup-log /path/to/retained-current-container-startup.log` records that file's
hash/path with its explicit provenance limitation. The operator must ensure this
retained log belongs to that exact current container. It must not be the v1 log.

Observed saved-log parser validation (read-only local evidence):

| Profile | Reported pool | Actual blocks | Blocks/1M request | Draft SW blocks |
| --- | ---: | ---: | ---: | ---: |
| v1 |7,101,928|2,578|363|25|
| fair-v2 |7,021,917|2,563|365|27|

Both contain MLA301, tail1 and four Mamba groups of9 blocks. Fair-v2 explicitly
logs batch/scheduled2304 and threshold256. Requested CLI block256 is distinct
from the observed effective attention block3328, which is recorded separately.

## Client integration

`longvision-c8.py run --runtime-evidence FILE` currently accepts **any JSON object**,
then copies and hashes it. It does not enforce this schema or validate the runtime.
Therefore require successful collection and review the resulting checks before
running the long client with the resulting file. No client code was changed.

`moderate-c8.py` has no runtime-evidence flag. Keep this artifact next to its output
and record the evidence SHA from the collector summary when associating that wave.
Do not infer live configuration from a prepared request or an environment file.

The long client's separate telemetry/usage/answer checks are still necessary to
establish actual simultaneous processed contexts and sustained common-window speed.
These results do not establish native-relative or broad benchmark accuracy.

Offline checks: `python3 test-collect-runtime-evidence.py` passed three groups:
real saved v1/v2 parser observations; duplicate-flag/secret filtering; mocked full
collection with0600 output and a negative offload case. No Docker was called.

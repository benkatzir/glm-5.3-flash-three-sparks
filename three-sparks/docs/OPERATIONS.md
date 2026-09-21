# Operations: how the three nodes are run

Sanitized from the operator runbook. Node addresses, interface names and the API key are
placeholders here; each node's private env file carries the real ones.

## Layout on every node

```
$GLM_ROOT/                     ours was /home/ben/glm53-lab
  models/target, target-tp3    pinned checkpoint and its TP3 padding sidecar (relative symlinks)
  models/draft, draft-tp3      pinned DFlash2 draft and its sidecar
  models/template/chat_template.jinja
  runtime/                     the patch tree the prelude runs (three-sparks/runtime/), with fixtures/
  overlay-v1/                  the two indexer files extracted from the image with upstream's
                               overlay + kpool + workspace patches pre-applied (read-only bind mounts)
  nccl-mesh/                   built mesh plugin (.so) and its SHA256SUMS
  runtime-cache/               tuner, triton, tilelang, flashinfer caches
  prep/                        the launcher, auth middleware and every test script
  private/                     rankN-<profile>.env (0600) and, on the head only, api-key (0600)
```

The launcher is [`prep/start-private-tp3.sh`](../prep/start-private-tp3.sh):
upstream's `start-tp3.sh` plus CDI GPU access, the auth middleware mount, the key-file preflight,
and a `DRY_RUN=1` mode that prints the full `docker run` line without running it. Every profile
change here was dry-run on each node and its output checked by script before any container moved.

## Profiles

All profiles use the same image, weights, patch tree and overlay. Each is one env file per node,
derived from the previous one by appending overrides (the file is sourced, last assignment wins).

| Profile | Containers | What changed | Status |
|---|---|---|---|
| v1 baseline | `glm53-v1-rN` | upstream settings at 0.88, video 0, eager | retained, stopped |
| fair-v2 | `glm53-v2-rN` | batch 2304, long-prefill threshold 256 | retained, stopped |
| fair-v3 | `glm53-v3-rN` | GPU memory fraction 0.80 | retained, stopped (video-off rollback) |
| **fair-v4** | `glm53-v4-rN` | video limit 2 | **serving** |
| scheduler control | `glm53-ctrl-rN` | batch 2048, no threshold (A/B only) | retained, stopped |

[`env/rank0-fair-v4.env.example`](../env/rank0-fair-v4.env.example)
is the head's v4 file with addresses replaced. Workers differ only in `NODE_RANK`, `HOST_IP` and
`NAME`. [`prep/make-node-env.py`](../prep/make-node-env.py) generates the v1
file from upstream's example; the later profiles are the appended blocks visible at the end of the
example.

## Switching profiles

Every profile occupies the same GPUs and the same head port, so stop the old cohort on all three
nodes before starting another. Order: stop with the queue idle, launch rank 2, then 1, then 0.

```bash
# on the head, confirm nothing is running or waiting
curl -s -H "Authorization: Bearer $(cat $GLM_ROOT/private/api-key)" http://127.0.0.1:8888/metrics \
  | grep -E '^vllm:num_requests_(running|waiting)'
# on each node
docker stop --timeout 30 glm53-v3-rN          # keep the container for rollback
# rank 2, then rank 1, then rank 0, as root
ENV_FILE=$GLM_ROOT/private/rankN-fair-v4.env bash $GLM_ROOT/prep/start-private-tp3.sh N
```

Cold boot to `/health` 200 takes 250 to 260 s. Read the boot log for the gate lines before trusting
the engine: `[padload]` and `preflight` PASS, `[vision-names] PASS`, `[video-geom] PASS`,
`HAREM-VISION: tower loaded … EXL3 linears=99, unquantized linears=0`, and the reported
`GPU KV cache size`. Then run, on the head:

```bash
python3 $GLM_ROOT/prep/probe-private-api.py --url http://127.0.0.1:8888 --key-file $GLM_ROOT/private/api-key
python3 $GLM_ROOT/prep/correctness-private.py --base http://127.0.0.1:8888 --api-key-file $GLM_ROOT/private/api-key
```

Rollback to any retained profile is the same sequence with `docker start` in place of the launcher.
No profile starts at boot (`--restart no`).

## Authentication

The head mounts the key file at `/run/secrets/glm-api-key`; `glm_private_auth.BearerMiddleware`
rejects every route and method without the bearer token except `GET/HEAD /health`, and websockets
are disabled. The key never appears in the environment, argv or logs. `VLLM_API_KEY` is deliberately
unset. Workers need no key.

## Long-context waves

The eight-way 500k client runs as a CPU-only container on the head (2 GiB, 2 CPUs, read-only,
no GPU) with a 90-minute deadline, and a separate memory guard polls `MemAvailable` on all three
nodes every 5 s over the fabric. Two consecutive readings below 3 GiB on any node send SIGINT to
the validated client container only; model containers are never targets, and stopping the guard
also stops its client so a wave never runs unguarded. Exact invocations are in
[`prep/longvision-c8.md`](../prep/longvision-c8.md) and
[`prep/longvision-memory-guard.md`](../prep/longvision-memory-guard.md).

Pause a wave by stopping the exact client container first, then its unit, then the guard unit, and
confirm the API's running and waiting counts return to zero before doing anything else. An
interrupted run does not produce `summary.json` and is not a qualification.

## What to watch

- `MemAvailable` on every node, not `MemFree`; swap traffic (`si`/`so`), not swap used.
- `vllm:num_preemptions_total` must stay 0 during a wave; a preemption at 500k is a restart of that
  prompt's prefill.
- After a video-heavy session the head's idle `MemAvailable` sits about 1 GiB lower; that is
  allocator retention, not a leak, and it was stable across the repeated batteries.

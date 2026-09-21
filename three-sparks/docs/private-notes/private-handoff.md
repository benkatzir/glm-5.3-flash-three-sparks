# Private deployment handoff

2026-09-20. All files prepared locally; this subtask did not SSH, stop an engine,
build an image, download weights, change a node, or run inference. Root handles
publication/rollback and deployment. These wrappers are an adaptation of recipe
7f1bd29 and require their own measured results.

## Directory layout and acquisition

Copy this preparation directory to `/home/ben/glm53-lab/prep` on each node.
Copy `prepared-runtime-7f1bd29/` separately to `/home/ben/glm53-lab/runtime/`.
Do not merge it with an existing runtime or alter an existing DeepSeek path.

The existing head download uses:

```bash
/home/ben/deepseek-lab/venv/bin/python3 /home/ben/glm53-lab/prep/download-models.py --root /home/ben/glm53-lab --workers 4
```

`download-manifest.json` records all 36 exact files and upstream LFS hashes:
target 165,151,543,361 bytes, draft 2,342,175,855 bytes, template 10,950 bytes.
Total 167,493,730,166 bytes / 155.991 GiB. `download-status.json` records verified
SHA256 values for all files, including small files checked against Git blob IDs.
Rerunning resumes Hugging Face incomplete transfers and rechecks completed files.
Use the resulting `models/{target,draft,template}` at identical paths on every
node; copy over the working fabric and verify destination SHA256 against the
completed status file. A file's existence or size alone is not verification.

## Build and stage

First source tree must remain cuda-exl3 754421fc99919317b9a4cf2928797bae8f870040.
Upstream did not publish its Dockerfile.gb10v8; our reconstruction is explicit.

```bash
docker build --memory=4g -f /home/ben/glm53-lab/prep/Dockerfile.serve-reconstructed -t glm53-local:serve-754421f /home/ben/glm53-lab/prep/cuda-exl3
docker build --memory=4g --build-arg BASE=glm53-local:serve-754421f -t glm53-local:754421f-dflash2 /home/ben/glm53-lab/prep/upstream/patches/dflash2-port
docker image inspect --format '{{.Id}}' glm53-local:754421f-dflash2
```

Record the resulting image ID, use that immutable ID in each config, transfer
the exact image to all three. Confirm the DFlash2 gate and pad-loader gate before
serving. Build concurrency is capped at three compile jobs; --memory is a Docker
builder setting, not a guarantee that every BuildKit driver enforces that limit.

Mesh plugin: build autoscriptlabs/nccl-mesh-plugin
19924dcc7c571d6e260953724d394ae50bad82cf with the upstream recipe's 0004/0005/0006
patches, run its CPU unit tests, place the resulting `libnccl-net-mesh.so` in
`/home/ben/glm53-lab/nccl-mesh/`. Preserve its exact source/patch/build identity.
Do not change host Docker daemon or fabric configuration. The pinned clean source
clone is included as `prep/nccl-mesh-source`; the following script checks its
commit, creates a separate build clone, applies patches in order, builds both
library names and runs `make test-unit`, without installing into system paths:

```bash
bash /home/ben/glm53-lab/prep/build-mesh.sh /home/ben/glm53-lab
```

Copy both `libnccl-net.so` and its `libnccl-net-mesh.so` symlink together to workers.
The patch application was checked locally against the pinned source; actual
compilation/unit execution still needs the Linux head and libibverbs headers.

For each node, after the image and runtime directory exist:

```bash
python3 /home/ben/glm53-lab/prep/stage-indexer.py --image IMAGE_ID --root /home/ben/glm53-lab
python3 /home/ben/glm53-lab/runtime/pad-tp3full.py /home/ben/glm53-lab/models/target /home/ben/glm53-lab/models/target-tp3 --tp 3
python3 /home/ben/glm53-lab/runtime/pad-tp3.py /home/ben/glm53-lab/models/draft /home/ben/glm53-lab/models/draft-tp3 --tp 3 --draft
```

Overlay staging runs one temporary CPU-only, network-disabled container. It
applies both top-k diffs, K-pool initialization and workspace patches, exports
the two read-only Python overlays, and records their hashes plus the image ID.
Startup repeats the patches against remaining in-image files idempotently.
It refuses an existing `overlay-v1/`; a failed attempt remains for inspection.

## Private serving configuration

Generate a private config individually on each node, using its actual management
IP/interface and the same head IP/image ID. Rank order is root's choice.

```bash
python3 /home/ben/glm53-lab/prep/make-node-env.py --root /home/ben/glm53-lab --rank RANK --host-ip NODE_MANAGEMENT_IP --head-ip HEAD_MANAGEMENT_IP --iface ACTUAL_INTERFACE --image IMAGE_ID --api-bind 0.0.0.0 --port 8888
```

First run uses explicit eager, TP3/EP, DFlash2 k7, index_topk8192, 1M max context,
eight max sequences, 0.88 memory utilization, and an empty FASTLOAD_MODE. Its
future fastload name is `fastload/fullscope-image-index8192-v1-rRANK` and a dump
refuses any existing nonempty directory. Do not enable `load` before a validated
dump matching all identity checks exists.

Vision is enabled with four images per prompt, **video disabled**. The published
repository omitted video fixtures. We retain its vision loader patches/gates and
do not claim its skipped video geometry gate passed. Initial PNG is outside the
runtime `fixtures/` directory, so it cannot accidentally trigger the video gate.

Provision the head's existing/private API key into
`/home/ben/glm53-lab/private/api-key` with mode0600; this generator never creates,
reads or logs a real key. Other ranks need no key file. The outer ASGI middleware
protects every route/method except GET/HEAD `/health`; websockets are disabled.
The key is read from a file mount and never placed in vLLM env/config/argv.
`VLLM_API_KEY` is explicitly unset to avoid redundant secret exposure. The pinned
built-in middleware alone would leave `/invocations` exposed.

Before LAN binding, run the included CPU auth gate. After LAN launch, run the
actual HTTP401 gate before treating the endpoint as deployed. The default bind
without `--api-bind` is127.0.0.1 for staging; the explicit command above serves the
LAN after these gates. Do not configure router forwarding.

```bash
python3 /home/ben/glm53-lab/prep/test-private-auth.py
ENV_FILE=/home/ben/glm53-lab/private/rankRANK.env bash /home/ben/glm53-lab/prep/start-private-tp3.sh RANK
```

Start2,1,0 only after root has preserved rollback, stopped all previous inference
ranks deliberately, and checked every node has adequate memory. This wrapper:

- Defaults to CDI `--device nvidia.com/gpu=all`, compatible with the actual
  runc-only Docker configuration. `GPU_MODE=legacy` is an explicit alternative.
- Refuses an existing `glm53-*` container; it never stops/removes a live container.
- Waits up to180seconds for MemAvailable≥112GiB, then **refuses** if below it.
- Verifies the image ID and overlay hashes before starting.
- Retains RDMA/IPC mounts, CPU affinity and transport from the upstream launcher.

## Authenticated gates and benchmark

All clients take a **key-file path**, never an inline key. Health is the only
public probe. Image probe output includes its answer and actual usage; inspect
the left/right relationship as well as the machine check for object/color words.

```bash
python3 /home/ben/glm53-lab/prep/probe-private-api.py --url http://127.0.0.1:8888 --key-file /home/ben/glm53-lab/private/api-key --auth-only
python3 /home/ben/glm53-lab/prep/probe-private-api.py --url http://127.0.0.1:8888 --key-file /home/ben/glm53-lab/private/api-key
python3 /home/ben/glm53-lab/prep/correctness-private.py --base http://127.0.0.1:8888 --api-key-file /home/ben/glm53-lab/private/api-key
python3 /home/ben/glm53-lab/prep/bench-private.py --base http://127.0.0.1:8888 --api-key-file /home/ben/glm53-lab/private/api-key --out /home/ben/glm53-lab/sweep-round1.json --label glm53-v1-round1 --think low
```

The copied benchmark preserves upstream's short-code prompts and timing formula,
adds auth to inference/metrics, refuses absent usage instead of counting SSE
chunks as tokens, and records all per-request results and failed-request counts.
Its repeated prefixes favor TTFT; its C6/C8 speeds do not prove independent500k
vision requests. Run at least three rounds with all requests passing.

The upstream code-exam still executes generated Python unsandboxed. This handoff
does not adapt or run it; root must run generated programs in a separate bounded
CPU container without network, secrets or host mounts before claiming its12/12.
Likewise, no C6/C8 500k vision test or matched native accuracy test has run yet.

## Completed local checks and unresolved runtime work

Passed: exact upstream-pinned indexer anchors and repeated idempotency; prepared
prelude shell syntax and all script references; private launcher shell syntax;
private env shell round-trip/effective eager, cold-load, image-only settings;
ASGI401 across methods/routes, duplicate-header refusal, authorized SSE event
passthrough, public health, websocket refusal and weak-key refusal. An independent
reviewer checked pinned vLLM CLI and headless/auth behavior. All local Python
files parse. Docker build/staging, real HTTP auth, compiled kernels, model loading,
runtime memory budget and final inference quality/performance remain untested.

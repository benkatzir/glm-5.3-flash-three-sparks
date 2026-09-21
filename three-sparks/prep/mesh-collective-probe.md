# Three-rank mesh collective probe

`mesh-collective-probe.py` checks every float32 element after all-reduce and all-gather. Inputs vary by rank, element, and round; integer-valued inputs and sums are exactly representable. Defaults: 17, 4,096, and 4,194,304 elements (68 bytes, 16 KiB, and 16 MiB per rank), two repeats, twelve checked stages. Each stage records collective and validation time. Any mismatch/error exits nonzero; a 60-second watchdog covers import, rendezvous, work, and teardown, with a separate 20-second distributed timeout.

Local preparation only: syntax and `--plan` checked; no GPU or remote execution performed. The probe does not load GLM or change any model runtime. Successful results qualify this bounded collective workload, not all transport behavior or model accuracy.

## Launch one independent Docker process on each Spark

Copy the Python file to the node's preparation directory. Use the already-built, identical plugin on all three nodes, and the exact serving image identity if available. If using only its pinned base image while the extension build completes, record that distinction and repeat in the final image before claiming final-image qualification.

On each node, set these existing deployment values: `GLM_ROOT` (that node's model root), `GLM_IMAGE` (image ID/tag), `GLM_MASTER_ADDR` (head management address), and `GLM_NODE_ADDR` (this node's management address). Set `GLM_RANK` to 0, 1, or 2. The management interface below is the verified `MGMT_IFACE`; RDMA uses the separate mesh fabric.

Choose the same unused rendezvous port for all three and start the three commands within a few seconds of each other. Root should dispatch them independently/concurrently, rather than waiting for one rank to exit before starting the next. Keep logs private because NCCL includes network identities.

```bash
GLM_PROBE_PORT=29577
GLM_PROBE_OUT="$GLM_ROOT/mesh-probe-r$GLM_RANK"
mkdir -p "$GLM_PROBE_OUT"
test ! -e "$GLM_PROBE_OUT/result.json"
test -f "$GLM_ROOT/nccl-mesh/libnccl-net-mesh.so"

docker run --rm --name "glm53-mesh-probe-r$GLM_RANK" \
  --device nvidia.com/gpu=all --device /dev/infiniband:/dev/infiniband \
  --network host --ipc host --shm-size 8g \
  --cpuset-cpus 5-9,15-19 --ulimit memlock=-1:-1 --cap-add IPC_LOCK \
  -v "$GLM_ROOT/nccl-mesh:/opt/nccl-mesh:ro" \
  -v "$GLM_ROOT/prep/mesh-collective-probe.py:/probe.py:ro" \
  -v "$GLM_PROBE_OUT:/probe-results" \
  -e VLLM_HOST_IP="$GLM_NODE_ADDR" \
  -e NCCL_CUMEM_ENABLE=0 -e NCCL_NVLS_ENABLE=0 \
  -e NCCL_CROSS_NIC=0 -e NCCL_IB_MERGE_NICS=0 \
  -e NCCL_IGNORE_CPU_AFFINITY=1 -e TORCH_NCCL_ASYNC_ERROR_HANDLING=1 \
  -e GLOO_SOCKET_IFNAME=MGMT_IFACE -e TP_SOCKET_IFNAME=MGMT_IFACE -e MN_IF_NAME=MGMT_IFACE \
  -e NCCL_NET=Mesh -e NCCL_NET_PLUGIN=mesh -e NCCL_IB_DISABLE=1 \
  -e NCCL_SOCKET_IFNAME='=MGMT_IFACE' -e NCCL_ALGO=Ring \
  -e NCCL_MAX_NCHANNELS=8 -e NCCL_MESH_LINKS_PER_PEER=0 \
  -e NCCL_MESH_MIN_RNR_TIMER=1 -e NCCL_MESH_PTR_CUDA=1 -e NCCL_MESH_FLUSH=1 \
  -e NCCL_MESH_DEBUG=1 -e NCCL_DEBUG=INFO -e NCCL_DEBUG_SUBSYS=INIT,NET \
  -e LD_LIBRARY_PATH=/opt/nccl-mesh \
  --entrypoint python3 "$GLM_IMAGE" -u /probe.py \
  --rank "$GLM_RANK" --master-addr "$GLM_MASTER_ADDR" --master-port "$GLM_PROBE_PORT" \
  --budget-seconds 60 --distributed-timeout-seconds 20 \
  --output /probe-results/result.json \
  > "$GLM_PROBE_OUT/container.log" 2>&1
```

No API key, model mount, model-launch prelude, network reconfiguration, or production container removal is involved. Repeated runs need a fresh output directory. If a host-side launch itself stalls before Python starts, stop only the explicitly named probe container; the Python watchdog begins when Python enters the probe, not during Docker image setup.

## Acceptance

Require all three Docker exits to be zero, all three JSON states to be `passed`, and twelve passed stages per rank. Each default run checks 33,587,336 received elements per rank. Confirm matching source/plugin hashes and serving-image identities. Record the initialization and stage durations as smoke-test timings, not optimized bandwidth claims.

Inspect logs for actual `Mesh` selection and real RDMA link use, absence of fallback, fatal events, work-completion errors, and timeouts. The JSON includes pre/post RDMA port counters and deltas; confirm the intended links transmitted and received. Other fabric activity can contribute to host counters, so counters alone do not prove that every increment came from the probe. The original six stale event-string unit failures remain recorded; this test does not rename that unit suite as fully passing.

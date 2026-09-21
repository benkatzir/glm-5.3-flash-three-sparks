#!/usr/bin/env bash
set -euo pipefail
RANK="${1:?rank required}"
case "$RANK" in
  0) IP=HEAD_MGMT_IP ;;
  1) IP=WORKER1_MGMT_IP ;;
  2) IP=WORKER2_MGMT_IP ;;
  *) exit 2 ;;
esac
LAB=/home/ben/glm53-lab
IMAGE=sha256:af1cd7490e0bd7f47c3ede8752e87625f3e080a4f5224d9191ca455aa56cdfbb
OUT="$LAB/mesh-probe-v1-r$RANK"
mkdir "$OUT"
exec docker run --pull=never --name "glm53-mesh-probe-v1-r$RANK" \
  --device nvidia.com/gpu=all --device /dev/infiniband:/dev/infiniband \
  --network host --ipc host --shm-size 8g \
  --cpuset-cpus 5-9,15-19 --ulimit memlock=-1:-1 --cap-add IPC_LOCK \
  -v "$LAB/nccl-mesh:/opt/nccl-mesh:ro" \
  -v "$LAB/prep/mesh-collective-probe.py:/probe.py:ro" \
  -v "$OUT:/probe-results" \
  -e VLLM_HOST_IP="$IP" \
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
  --entrypoint python3 "$IMAGE" -u /probe.py \
  --rank "$RANK" --master-addr HEAD_MGMT_IP --master-port 29577 \
  --budget-seconds 60 --distributed-timeout-seconds 20 \
  --output /probe-results/result.json > "$OUT/container.log" 2>&1

#!/usr/bin/env bash
# Does not start a model, expose GPUs, alter Docker daemon, or pull an image.
set -euo pipefail
GLM_LAB_ROOT="${1:?usage: build-wheel-bounded.sh /home/ben/glm53-lab [attempt-label]}"
GLM_ATTEMPT="${2:-v2}"
[[ "$GLM_ATTEMPT" =~ ^[a-zA-Z0-9_.-]+$ ]] || { echo "Invalid attempt label" >&2; exit 2; }
GLM_PREP_DIR="$(cd "$(dirname "$0")" && pwd)"
GLM_SOURCE_PIN=754421fc99919317b9a4cf2928797bae8f870040
GLM_BASE='vllm/vllm-openai@sha256:905c02933be6021301db2dc284e24e3727467aa3a0f63b41d609885778a07bce'
GLM_BASE_ID="$(docker image inspect --format '{{.Id}}' "$GLM_BASE")"
GLM_CONTEXT="$GLM_LAB_ROOT/build/wheel-image-$GLM_ATTEMPT"
GLM_WORK="$GLM_LAB_ROOT/build/wheel-work-$GLM_ATTEMPT"
GLM_CONTAINER="glm53-wheel-754421f-$GLM_ATTEMPT"
test "$(git -C "$GLM_PREP_DIR/cuda-exl3" rev-parse HEAD)" = "$GLM_SOURCE_PIN"
test -z "$(git -C "$GLM_PREP_DIR/cuda-exl3" status --porcelain)" || { echo "Pinned source clone is dirty" >&2; exit 2; }
test ! -e "$GLM_CONTEXT" && test ! -e "$GLM_WORK" || { echo "Refusing existing wheel context/work directory" >&2; exit 2; }
if docker container inspect "$GLM_CONTAINER" >/dev/null 2>&1; then
  echo "Refusing existing compile container $GLM_CONTAINER" >&2; exit 2
fi
mkdir -p "$GLM_CONTEXT/source" "$GLM_CONTEXT/wheelhouse" "$GLM_WORK"
git -C "$GLM_PREP_DIR/cuda-exl3" archive "$GLM_SOURCE_PIN" | tar -x -C "$GLM_CONTEXT/source"
cp -a "$GLM_CONTEXT/source" "$GLM_WORK/source"
cp "$GLM_PREP_DIR/Dockerfile.serve-wheel" "$GLM_CONTEXT/Dockerfile"
cp "$GLM_PREP_DIR/verify-installed-exl3.py" "$GLM_CONTEXT/verify-installed-exl3.py"
docker create --pull=never --name "$GLM_CONTAINER" --runtime runc \
  --memory=6g --memory-swap=6g --cpus=3 --pids-limit=512 \
  --network=host --entrypoint bash \
  -e MAX_JOBS=2 -e TORCH_CUDA_ARCH_LIST=12.1 -e PIP_NO_INDEX=1 \
  -e GLM_BUILD_IMAGE_ID="$GLM_BASE_ID" \
  -v "$GLM_WORK/source:/build/source" \
  -v "$GLM_CONTEXT/wheelhouse:/wheelhouse" \
  -v "$GLM_PREP_DIR:/prep:ro" \
  "$GLM_BASE_ID" /prep/wheel-build-entry.sh
docker inspect --format '{{json .HostConfig}}' "$GLM_CONTAINER" | python3 -c '
import json,sys
c=json.load(sys.stdin)
assert c["Memory"]==6*2**30 and c["MemorySwap"]==6*2**30 and c["NanoCpus"]==3*10**9
assert not c.get("DeviceRequests") and not c.get("Devices"), "Compile must not expose GPUs"
print("Verified Docker compile limits:6GiB RAM,0 swap,3CPU; no GPU requests",flush=True)
'
# Container intentionally retained after completion/failure for logs and OOM state.
# Stopping this shell alone does not stop its container; root may docker stop it.
GLM_BUILD_RC=0
docker start -a "$GLM_CONTAINER" || GLM_BUILD_RC=$?
docker inspect --format '{{json .State}}' "$GLM_CONTAINER" > "$GLM_CONTEXT/builder-state.json"
python3 - "$GLM_CONTEXT/builder-state.json" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
assert s['ExitCode']==0 and not s['OOMKilled'], s
PY
test "$GLM_BUILD_RC" -eq 0
test -f "$GLM_CONTEXT/wheelhouse/wheel-build-manifest.json"
echo "Verified wheel context: $GLM_CONTEXT"
echo "Compile container retained: $GLM_CONTAINER"

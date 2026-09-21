#!/usr/bin/env bash
# Replay the REAL boot prelude (tp3-prelude.sh, same patch order, same env knobs,
# same read-only overlay mounts as start-private-tp3.sh) in a throwaway CPU
# container, with the final `exec vllm serve` replaced by an echo. No GPU, no
# engine, safe while production serves. The vision block then runs all three
# model-free gates including check-video-geometry.py over $TP3_DIR/fixtures.
#
# Usage (root on the head):  ENV_FILE=/home/ben/glm53-lab/private/rank0-fair-v4.env bash run-video-gate-cpu.sh
set -euo pipefail
ENV_FILE="${ENV_FILE:?}"
source "$ENV_FILE"
: "${IMAGE:?}" "${TP3_DIR:?}" "${MODEL_HOST_PATH:?}" "${MODEL_LINK_TARGET:?}" "${DRAFT_HOST_PATH:?}" "${DRAFT_LINK_TARGET:?}" "${OVERLAY_DIR:?}"
test -d "$TP3_DIR/fixtures" || { echo "no fixtures under $TP3_DIR/fixtures -- the gate would be SKIPPED, refusing" >&2; exit 2; }
WORK="$(mktemp -d /tmp/cpu-gate.XXXXXX)"
sed 's|^exec vllm serve "\$@"$|echo "[cpu-gate] PRELUDE_COMPLETE (vllm serve not started)"|' "$TP3_DIR/tp3-prelude.sh" > "$WORK/start.sh"
grep -q 'PRELUDE_COMPLETE' "$WORK/start.sh" || { echo "failed to neutralise exec line" >&2; exit 2; }
VP=/usr/local/lib/python3.12/dist-packages/vllm
OVERLAY_MOUNT=()
for f in sparse_attn_indexer_kpool.py sparse_attn_indexer.py; do
  [ -f "$OVERLAY_DIR/$f" ] && OVERLAY_MOUNT+=(-v "$OVERLAY_DIR/$f:$VP/model_executor/layers/$f:ro")
done
EXTRA_ENV_ARG=(); for _kv in ${EXTRA_ENV:-}; do EXTRA_ENV_ARG+=(-e "$_kv"); done
docker run --rm --name glm53-cpu-gate-video --memory 6g --memory-swap 6g --cpuset-cpus 0-3 --network none \
  -v "$MODEL_HOST_PATH:$MODEL_HOST_PATH:ro" -v "$MODEL_LINK_TARGET:$MODEL_LINK_TARGET:ro" \
  -v "$DRAFT_HOST_PATH:$DRAFT_HOST_PATH:ro" -v "$DRAFT_LINK_TARGET:$DRAFT_LINK_TARGET:ro" \
  -v "$TP3_DIR:/opt/harem-tp3:ro" -v "$WORK/start.sh:/start.sh:ro" "${OVERLAY_MOUNT[@]}" \
  -e TP3_DIR=/opt/harem-tp3 -e NODE_RANK=0 -e TP_SIZE=3 -e ENABLE_EP=1 -e TP3_STRICT=1 \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e CUDA_EXL3_DEBUG_NAMES=1 \
  -e HAREM_FLASHINFER_WARMUP=0 "${EXTRA_ENV_ARG[@]}" \
  --entrypoint bash "$IMAGE" /start.sh "$MODEL_HOST_PATH" 2>&1 | grep -vE '^(INFO|WARNING) [0-9]|^W[0-9]{4} '
rc=${PIPESTATUS[0]}
rm -rf "$WORK"
echo "[cpu-gate] container exit code $rc"
exit $rc

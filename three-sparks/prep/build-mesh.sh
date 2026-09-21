#!/usr/bin/env bash
# Source build only. No installation into system paths or network changes.
set -euo pipefail
GLM_LAB_ROOT="${1:?usage: build-mesh.sh /home/ben/glm53-lab}"
GLM_PREP_DIR="$(cd "$(dirname "$0")" && pwd)"
GLM_MESH_PIN=19924dcc7c571d6e260953724d394ae50bad82cf
GLM_MESH_BUILD="$GLM_LAB_ROOT/build/nccl-mesh-19924dcc-p456"
GLM_MESH_OUT="$GLM_LAB_ROOT/nccl-mesh"
test ! -e "$GLM_MESH_BUILD" && test ! -e "$GLM_MESH_OUT" || { echo "Refusing existing build/output directory" >&2; exit 2; }
test "$(git -C "$GLM_PREP_DIR/nccl-mesh-source" rev-parse HEAD)" = "$GLM_MESH_PIN"
pkg-config --exists libibverbs || { echo "Missing libibverbs development headers/pkg-config metadata" >&2; exit 2; }
mkdir -p "$GLM_LAB_ROOT/build"
git clone --no-hardlinks "$GLM_PREP_DIR/nccl-mesh-source" "$GLM_MESH_BUILD"
git -C "$GLM_MESH_BUILD" checkout --detach "$GLM_MESH_PIN"
for patch_name in 0004-min-rnr-timer.patch 0005-device-aware-link-selection.patch 0006-ptr-cuda-dmabuf-and-flush.patch; do
  git -C "$GLM_MESH_BUILD" apply --check "$GLM_PREP_DIR/upstream/patches/kernel/$patch_name"
  git -C "$GLM_MESH_BUILD" apply "$GLM_PREP_DIR/upstream/patches/kernel/$patch_name"
done
make -C "$GLM_MESH_BUILD" -j2 all
# Pinned Makefile omits libibverbs from TEST_LDFLAGS; the tests reference
# ibv_event_type_str on the actual Spark. Serving-library flags are unchanged.
make -C "$GLM_MESH_BUILD" test-unit TEST_LDFLAGS='-lpthread -libverbs'
mkdir "$GLM_MESH_OUT"
cp "$GLM_MESH_BUILD/libnccl-net.so" "$GLM_MESH_OUT/libnccl-net.so"
ln -s libnccl-net.so "$GLM_MESH_OUT/libnccl-net-mesh.so"
git -C "$GLM_MESH_BUILD" diff > "$GLM_MESH_OUT/applied-source.diff"
sha256sum "$GLM_MESH_OUT/libnccl-net.so" "$GLM_MESH_OUT/applied-source.diff" > "$GLM_MESH_OUT/SHA256SUMS"
echo "Built private mesh plugin: $GLM_MESH_OUT"

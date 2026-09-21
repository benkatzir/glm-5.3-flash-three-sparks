#!/usr/bin/env python3
"""Generate a reviewed launcher adaptation; never invokes Docker or SSH."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parent


def main():
    source = ROOT / "upstream/scripts/start-tp3.sh"
    dest = ROOT / "start-private-tp3.sh"
    text = source.read_text()

    def change(old, new):
        nonlocal text
        if text.count(old) != 1:
            raise RuntimeError("Launcher anchor mismatch: " + old[:70])
        text = text.replace(old, new, 1)

    change('NAME="${NAME:-exl3-tp3}"', '''NAME="${NAME:?set a GLM-specific NAME}"
[[ "$NAME" =~ ^glm53-[a-zA-Z0-9_.-]+$ ]] || { echo "NAME must begin glm53-" >&2; exit 2; }
AUTH_DIR="${AUTH_DIR:?}"
API_BIND="${API_BIND:-127.0.0.1}"
AUTH_MOUNT=(-v "$AUTH_DIR:/opt/glm-auth:ro")
if [ "$NODE_RANK" = 0 ]; then
  test -f "${API_KEY_FILE:?}" || { echo "Missing private API key file" >&2; exit 2; }
  python3 - "$API_KEY_FILE" <<'PY'
import os, pathlib, stat, sys
p = pathlib.Path(sys.argv[1]); st = p.stat(); key = p.read_bytes().strip()
assert stat.S_ISREG(st.st_mode) and not st.st_mode & 0o077, "Key permissions must be 0600 or stricter"
assert 32 <= len(key) <= 512 and key.isascii() and all(c > 32 for c in key), "Invalid key format"
PY
  AUTH_MOUNT+=(-v "$API_KEY_FILE:/run/secrets/glm-api-key:ro")
fi''')
    change('DOCKER_ARGS=(run --gpus all -d', '''GPU_MODE="${GPU_MODE:-cdi}"
case "$GPU_MODE" in
  cdi) GPU_ARGS=(--device nvidia.com/gpu=all) ;;
  legacy) GPU_ARGS=(--gpus all) ;;
  *) echo "GPU_MODE must be cdi or legacy" >&2; exit 2 ;;
esac
DOCKER_ARGS=(run "${GPU_ARGS[@]}" -d''')
    change('    dump) mkdir -p "$_FL"; FASTLOAD_MOUNT=(-v "$_FL:$_FL") ;;', '''    dump) if [ -d "$_FL" ] && [ -n "$(find "$_FL" -mindepth 1 -print -quit)" ]; then
            echo "Refusing existing nonempty fastload dump: $_FL" >&2; exit 2
          fi
          mkdir -p "$_FL"; FASTLOAD_MOUNT=(-v "$_FL:$_FL") ;;''')
    change('  "${PLUGIN_MOUNT[@]}" "${OVERLAY_MOUNT[@]}" "${FASTLOAD_MOUNT[@]}"', '  "${PLUGIN_MOUNT[@]}" "${OVERLAY_MOUNT[@]}" "${FASTLOAD_MOUNT[@]}" "${AUTH_MOUNT[@]}"\n  -e PYTHONPATH=/opt/glm-auth -e GLM_API_KEY_FILE=/run/secrets/glm-api-key')
    change('--entrypoint bash "$IMAGE" /start.sh "$MODEL_PATH"', '--entrypoint bash "$IMAGE" /opt/glm-auth/private-entry.sh "$MODEL_PATH"')
    change('--host 0.0.0.0', '--host "$API_BIND"')
    change('[ -n "${EXTRA_ARGS:-}" ] && DOCKER_ARGS+=(${EXTRA_ARGS})', '''[ -n "${EXTRA_ARGS:-}" ] && DOCKER_ARGS+=(${EXTRA_ARGS})
# Final flags prevent EXTRA_ARGS from dropping authentication or changing bind.
DOCKER_ARGS+=(--host "$API_BIND" --middleware glm_private_auth.BearerMiddleware --disable-fastapi-docs --no-enable-log-requests)''')
    change('docker rm -f "$NAME" 2>/dev/null || true', '''if docker container inspect "$NAME" >/dev/null 2>&1; then
  echo "Refusing existing container $NAME; root must deliberately stop/remove it before launch" >&2
  exit 2
fi
python3 "$AUTH_DIR/verify-overlay.py" --image "$IMAGE" --overlay "$OVERLAY_DIR"''')
    change('docker "${DOCKER_ARGS[@]}"', '''if [ "$settle_avail" -lt "$SETTLE_MIN_GIB" ]; then
  echo "REFUSED: MemAvailable remains below ${SETTLE_MIN_GIB} GiB; no container started" >&2
  exit 3
fi
docker "${DOCKER_ARGS[@]}"''')
    dest.write_text(text)
    dest.chmod(0o755)
    subprocess.run(["bash", "-n", str(dest)], check=True)
    (ROOT / "private-launch-manifest.json").write_text(json.dumps({"upstream_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "adapted_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(), "changes": ["all-route file-key auth and loopback default", "explicit private namespace", "refuse existing containers", "refuse memory-settle timeout", "refuse nonempty dump target", "verify image/overlay identity"]}, indent=2) + "\n")


if __name__ == "__main__":
    main()

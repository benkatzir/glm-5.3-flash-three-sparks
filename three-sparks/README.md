# three-sparks/: everything this deployment added on top of upstream

| Directory | What it is |
|---|---|
| [`runtime/`](runtime/) | The patch tree mounted at `/opt/harem-tp3` and run by the prelude on every boot: upstream's `tracks/tp3/patches` flattened into one directory with the vision hook and the xgrammar backport call inserted, plus `fixtures/` for the video geometry gate |
| [`prep/`](prep/) | Every script as deployed on the nodes, in the same flat layout (`$GLM_ROOT/prep/`), because the scripts find their data files next to themselves. `prep/upstream` is a symlink to the repository root, which is where the nodes had the upstream checkout |
| [`env/`](env/) | The head node's serving env file with addresses replaced |
| [`results/`](results/) | Sanitized copies of the evidence the tests wrote ([index](results/README.md)) |
| [`docs/`](docs/) | Benchmarks, limitations, deviations from upstream, provenance, operations, video, timeline; `private-notes/` holds the preparation and review notes as written before deployment |
| [`licenses/`](licenses/) | Licences of the third-party components the build pulls in |
| `source-lock.json`, [`scripts/verify_sources.py`](scripts/verify_sources.py) | SHA-256 of every file in this directory and a checker |

## What is in `prep/`

| Role | Files |
|---|---|
| Launch | `start-private-tp3.sh` (upstream's launcher plus CDI GPU access, bearer auth, dry-run), `private-entry.sh`, `glm_private_auth.py`, `make-node-env.py`, `prepare-private-launch.py`, `stage-indexer.py`, `verify-overlay.py`, `video/mkv4-env.py`, `video/mkctrl-env.py` |
| Build | `Dockerfile.serve-reconstructed`, `Dockerfile.serve-wheel`, `build-wheel-bounded.sh`, `wheel-build-entry.sh`, `verify-exl3-wheel.py`, `verify-installed-exl3.py`, `build-mesh.sh`, `prepare-local-tree.py`, `source-pins.json`, `manifests/` |
| Acquisition | `download-models.py`, `download-manifest.json`, `hf-file-metadata.json`, `partition-download-manifest*.py`, `verify-models.py` |
| Gates | `probe-private-api.py`, `correctness-private.py`, `code-exam-private.py`, `gpu-core-gate.py`, `mesh-collective-probe.py`, `run-mesh-probe-private.sh`, `smoke-fixtures/` |
| Benchmarks | `bench-private.py` with `hizset-v2.jsonl`, `run-sweep-three-rounds.py`, `moderate-c8.py`, `longvision-c8.py`, `longvision-memory-guard.py`, `collect-runtime-evidence.py`, `status-long-fair-v3.py` |
| Video | `video/make-video-fixtures.py`, `video/run-video-gate-cpu.sh`, `video/video-tests.py`, `video/video-diag.py`, `video/make-diag-clips.py`, `video/pixelhash.py` |
| Unit tests | `test-*.py` (no GPU, no network) |

Node addresses and the management interface name appear as `HEAD_MGMT_IP`, `WORKER1_MGMT_IP`,
`WORKER2_MGMT_IP`, `WORKER1_FABRIC_IP`, `WORKER2_FABRIC_IP` and `MGMT_IFACE` in
`longvision-memory-guard.py`, `mesh-collective-probe.py`, `run-mesh-probe-private.sh` and
`video/video-tests.py`. Replace them with your own before running those four.

Verify a checkout:

```bash
python3 three-sparks/scripts/verify_sources.py
```

The narrative, numbers and limits start at the repository root: [README.md](../README.md).

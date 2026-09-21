# Bounded wheel build, revision2

This supersedes the **image compilation** commands in `private-handoff.md`.
The serving profile and checkpoint pins are unchanged. The prior Dockerfile
compiled under BuildKit, whose `--memory` setting was ignored on the actual host.
A memory limit on the Docker client also does not cap its daemon's compile work.

The new path compiles inside an ordinary Docker container with **6GiB RAM,
zero swap, three CPUs, MAX_JOBS=2** and no GPU devices. It checks HostConfig before
start and the actual cgroup-v2 `memory.max`, `memory.swap.max`, and `cpu.max`
inside the compiler before invoking pip. The base is already local; `--pull=never`
and its resolved local image ID prevent another download. No buildx builder or
new Docker daemon is created. Source and compiler intermediates are writable
copies outside the frozen clone. There is no inference/model operation.

Copy these new/updated prep files to the head:

- `build-wheel-bounded.sh`, `wheel-build-entry.sh`, `verify-exl3-wheel.py`
- `Dockerfile.serve-wheel`, `verify-installed-exl3.py`
- `build-mesh.sh` (unit-test link fix described below)

Then run using the root's existing detached/logged execution method:

```bash
bash /home/ben/glm53-lab/prep/build-wheel-bounded.sh /home/ben/glm53-lab v1
```

Compile container: `glm53-wheel-754421f-v1`, intentionally retained for logs and
OOM inspection. Stopping the shell does not stop that container; use
`docker stop glm53-wheel-754421f-v1` to interrupt actual compilation. A retry uses
a new label (`v2`) to preserve the failed output. Do not increase its memory
limit merely to get past an OOM while the serving engine remains live.

Verified output context:
`/home/ben/glm53-lab/build/wheel-image-v1`.
The manifest is `wheelhouse/wheel-build-manifest.json`, with wheel SHA256,
base-image ID, source commit, module names, CUDA architecture and build limits.
`builder-state.json` records exit/OOM state even when the compile fails.

After the bounded wheel step passes:

```bash
docker build --pull=false --network=none -t glm53-local:serve-wheel754421f-v1 /home/ben/glm53-lab/build/wheel-image-v1
docker build --pull=false --network=none --build-arg BASE=glm53-local:serve-wheel754421f-v1 -t glm53-local:wheel754421f-dflash2-v1 /home/ben/glm53-lab/prep/upstream/patches/dflash2-port
docker image inspect --format '{{.Id}}' glm53-local:wheel754421f-dflash2-v1
```

Use the existing default Docker builder; do not create a buildx container.
The first layer verifies the wheel hash and installs it with `--no-index
--no-deps --force-reinstall`. It performs CPU imports/module checks, with **no
compiler invocation**. DFlash2 only copies Python files and runs its existing
symbol gate. Those lightweight image steps are still BuildKit operations; the
6GiB guarantee specifically covers the expensive compiler container.

Export this one final image and transfer it to both workers. Generate configs
and indexer overlays against the **new final image ID**, never the earlier direct
build tag. Preserve the prepared runtime, model sidecars, API8888/CDI/auth setup.
The prior instruction to leave fastload mode empty still applies.

## Package completeness and runtime equivalence

At source754421f, `pyproject.toml` uses `src/` layout with the complete explicit
`cuda_exl3` package and its `vllm.general_plugins` entry point. `setup.py` compiles
`cuda_exl3._C` from `bindings.cpp`, `hadamard.cu`, `gemm.cu`, and `mla_decode.cu`.
It can silently emit a pure-Python package if sources are missing, so our gate
explicitly refuses a wheel without the compiled extension.

The verifier checks **every top-level source Python module byte-for-byte** in
the wheel, the plugin entry point, ELF64 AArch64 identity, non-pure ARM wheel
metadata, and the native cubin architecture (`sm_121` only via cuobjdump). The
install gate rechecks source modules at the expected `dist-packages` path,
imports the native extension, and confirms its Torch operator is registered.
The exact clean source is retained at `/opt/cuda-exl3` for diagnostics and tests;
those repository scripts are intentionally not wheel entry points. The runtime
patch tree acts on installed modules and does not require code from that source
directory. CUDA headers/sources are compilation inputs, not runtime-loaded files.

The pinned base, package source, compiler options, torch/ABI dependencies and
sm_121 target remain the same as the intended direct pip build. Splitting wheel
creation from installation changes build location and scheduling, so **binary
identity with the unpublished original build is not claimed**. The new image is
explicitly named and labeled `bounded-wheel-6g-maxjobs2-v1`; real kernel and model
gates are still required after the image exists.

## Mesh unit-test link fix

The actual Spark built the serving mesh library successfully, but its pinned
Makefile's unit-test link line omitted libibverbs and failed on
`ibv_event_type_str`. `build-mesh.sh` now uses:

```bash
make -C /home/ben/glm53-lab/build/nccl-mesh-19924dcc-p456 test-unit TEST_LDFLAGS='-lpthread -libverbs'
```

This only fixes test linkage. No serving source, plugin compiler flags or
0004/0005/0006 patch changes were introduced.

Prepared locally only. Shell/Python syntax and source/package references were
checked; this subtask did not SSH or execute the compiler/container/image steps.

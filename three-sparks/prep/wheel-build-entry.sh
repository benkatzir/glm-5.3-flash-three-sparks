#!/usr/bin/env bash
set -euo pipefail
umask 022
# These are the actual compile process cgroups, not limits on a Docker client.
python3 - <<'PY'
from pathlib import Path
import importlib.metadata as m
import json
import platform
assert platform.machine() == "aarch64", "Use the Spark ARM64 builder"
memory = Path('/sys/fs/cgroup/memory.max').read_text().strip()
swap = Path('/sys/fs/cgroup/memory.swap.max').read_text().strip()
quota, period = map(int, Path('/sys/fs/cgroup/cpu.max').read_text().split())
assert memory == str(6 * 2**30), f"Memory cgroup is {memory}, expected6GiB"
assert swap == '0', f"Swap cgroup is {swap}, expected0"
assert quota / period == 3, f"CPU cgroup is {quota}/{period}, expected3"
# setuptools80.10.2 exposes its vendored wheel only after import. A missing
# standalone wheel distribution is not a missing backend and must not make a
# version-printing diagnostic abort the build. Check the actual backend imports.
import setuptools
from setuptools.command.bdist_wheel import bdist_wheel
from wheel.wheelfile import WheelFile
import wheel
versions = {n:m.version(n) for n in ['torch','setuptools','numpy','vllm']}
try:
    versions['wheel_distribution'] = m.version('wheel')
except m.PackageNotFoundError:
    versions['wheel_distribution'] = None
versions['wheel_module'] = wheel.__version__
print(json.dumps({'memory_max': memory, 'swap_max': swap, 'cpu_quota': quota, 'cpu_period': period, 'versions': versions, 'wheel_origin': wheel.__file__, 'backend_imports': 'passed'}), flush=True)
PY
test "${MAX_JOBS:?}" = 2
test "${TORCH_CUDA_ARCH_LIST:?}" = 12.1
cd /build/source
python3 -m pip wheel --no-index --no-build-isolation --no-deps --no-cache-dir --wheel-dir /wheelhouse .
python3 /prep/verify-exl3-wheel.py --source /build/source --wheelhouse /wheelhouse

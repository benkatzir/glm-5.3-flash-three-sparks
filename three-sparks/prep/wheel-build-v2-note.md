# Bounded wheel attempt v2: minimal diagnostic fix

The first attempt stopped before compilation because our preflight asked
`importlib.metadata.version('wheel')` for a standalone distribution that was not
present in the base. That does **not** establish a missing wheel backend.

The actual base has setuptools80.10.2. Its exact upstream source adds
`setuptools/_vendor` to `sys.path` when setuptools is imported, vendors wheel0.46.3,
and imports `wheel.wheelfile.WheelFile` from `setuptools.command.bdist_wheel`.
The original diagnostic ran before that import. The pinned cuda-exl3 project
does list wheel in `build-system.requires`; with build isolation disabled, the
existing backend must be usable, and importing the backend is the relevant check.

The updated preflight imports setuptools, bdist_wheel and WheelFile; records the
actual wheel module version/path; and treats absent standalone distribution
metadata as `null`. It adds **no dependency, pip upgrade, source change, network
access or runtime package change**. Root verified these exact imports in the actual base: all passed, resolving
wheel0.46.3 from `/usr/local/lib/python3.12/dist-packages/setuptools/_vendor/wheel/__init__.py`.
The real offline pip-wheel build remains the next proof that these components
work together.

Exact primary sources inspected:

- https://github.com/pypa/setuptools/blob/v80.10.2/setuptools/__init__.py
- https://github.com/pypa/setuptools/blob/v80.10.2/setuptools/command/bdist_wheel.py
- https://github.com/pypa/setuptools/blob/v80.10.2/setuptools/_vendor/wheel/__init__.py

Copy updated `wheel-build-entry.sh`, `build-wheel-bounded.sh` and
`Dockerfile.serve-wheel` to the head prep directory, preserving the failed
`glm53-wheel-754421f-v1` container and `wheel-image-v1`/`wheel-work-v1` paths.

```bash
bash /home/ben/glm53-lab/prep/build-wheel-bounded.sh /home/ben/glm53-lab v2
docker build --pull=false --network=none -t glm53-local:serve-wheel754421f-v2 /home/ben/glm53-lab/build/wheel-image-v2
docker build --pull=false --network=none --build-arg BASE=glm53-local:serve-wheel754421f-v2 -t glm53-local:wheel754421f-dflash2-v2 /home/ben/glm53-lab/prep/upstream/patches/dflash2-port
```

Run each step only after the previous succeeds. Actual compile limits remain
6GiB RAM, zero swap, three CPUs and MAX_JOBS2, verified from its cgroups. New
container `glm53-wheel-754421f-v2`; its build method label ends in `v2`.

If the actual backend import fails, pause before compilation and inspect that
specific missing dependency. A verified offline wheel0.45.1 artifact is available
from PyPI (Python≥3.8, no mandatory dependencies), but this preparation has not
downloaded or installed it because the existing vendored backend may suffice.

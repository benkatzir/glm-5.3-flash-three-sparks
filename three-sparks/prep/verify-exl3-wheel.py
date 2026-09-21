#!/usr/bin/env python3
"""Verify wheel payload against pinned source; no CUDA device access."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import tempfile
import zipfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--wheelhouse", type=Path, required=True)
    a = p.parse_args()
    wheels = list(a.wheelhouse.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"Expected one wheel, found {len(wheels)}")
    wheel = wheels[0]
    if platform.machine() != "aarch64":
        raise SystemExit("Verify the actual wheel on the ARM64 Spark builder")
    expected = sorted((a.source / "src/cuda_exl3").glob("*.py"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for source in expected:
            name = "cuda_exl3/" + source.name
            if archive.read(name) != source.read_bytes():
                raise SystemExit("Missing or changed Python module: " + name)
        extensions = [name for name in names if re.fullmatch(r"cuda_exl3/_C\.[^/]+\.so", name)]
        if len(extensions) != 1:
            raise SystemExit("Expected one compiled cuda_exl3._C extension; pure-Python fallback refused")
        native = archive.read(extensions[0])
        if native[:4] != b"\x7fELF" or native[4] != 2:
            raise SystemExit("Extension is not ELF64")
        byteorder = "<" if native[5] == 1 else ">"
        if struct.unpack(byteorder + "H", native[18:20])[0] != 183:
            raise SystemExit("Extension is not AArch64")
        entrypoints = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(entrypoints) != 1:
            raise SystemExit("Missing plugin entry-point metadata")
        config = configparser.ConfigParser()
        config.read_string(archive.read(entrypoints[0]).decode())
        if config["vllm.general_plugins"]["cuda_exl3"] != "cuda_exl3:register":
            raise SystemExit("Incorrect vLLM plugin entry point")
        metadata = [name for name in names if name.endswith(".dist-info/WHEEL")]
        wheel_metadata = archive.read(metadata[0]).decode()
        if "Root-Is-Purelib: false" not in wheel_metadata or "aarch64" not in wheel_metadata:
            raise SystemExit("Wheel platform metadata does not describe an ARM64 extension")
        with tempfile.TemporaryDirectory() as temp:
            extension = Path(temp) / "cuda_exl3_C.so"
            extension.write_bytes(native)
            listing = subprocess.check_output(["/usr/local/cuda/bin/cuobjdump", "--list-elf", str(extension)], text=True, stderr=subprocess.STDOUT)
        arches = sorted(set(re.findall(r"sm_([0-9]+)", listing)))
        if arches != ["121"]:
            raise SystemExit(f"Expected sm_121 only, got {arches}")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (a.wheelhouse / "SHA256SUMS").write_text(f"{digest}  {wheel.name}\n")
    manifest = {
        "wheel": wheel.name, "sha256": digest, "bytes": wheel.stat().st_size,
        "source_commit": "754421fc99919317b9a4cf2928797bae8f870040",
        "base_image_id": os.environ.get("GLM_BUILD_IMAGE_ID"),
        "python_modules_verified": [source.name for source in expected],
        "native_extension": extensions[0], "native_cpu": "aarch64", "cuda_arches": arches,
        "entrypoint": "cuda_exl3:register", "build_memory_bytes": 6 * 2**30,
        "build_swap_bytes": 0, "build_cpus": 3, "max_jobs": 2,
    }
    (a.wheelhouse / "wheel-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()

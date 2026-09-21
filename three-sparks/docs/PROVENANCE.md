# Provenance

Everything below was pinned before acquisition and verified after it. The deployment ran on
three NVIDIA DGX Sparks (GB10, 128 GB unified memory each) joined by three direct QSFP cables in
a triangle, each cable carrying two logical RoCE links, exactly the topology upstream describes.

## The recipe this continues

| Source | Revision |
|---|---|
| [NNNtrance/GLM-5.3-Flash-EXL3-DGX-Spark](https://github.com/NNNtrance/GLM-5.3-Flash-EXL3-DGX-Spark) | `7f1bd29cf473548212b8b731c52dcf2c7aa5a033` (this repository's git history up to that commit is upstream's) |
| [Zeuss5/cuda-exl3](https://github.com/Zeuss5/cuda-exl3) | `754421fc99919317b9a4cf2928797bae8f870040`, built from source into the image |
| [autoscriptlabs/nccl-mesh-plugin](https://github.com/autoscriptlabs/nccl-mesh-plugin) | `19924dcc7c571d6e260953724d394ae50bad82cf` plus upstream's `patches/kernel` 0004, 0005, 0006; built library `sha256 8bed8246…`, applied-source diff `f43289f3…` ([results/mesh](../results/mesh/)) |
| vLLM base image `vllm/vllm-openai` | `sha256:905c02933be6021301db2dc284e24e3727467aa3a0f63b41d609885778a07bce` |
| Serving image built here | `sha256:af1cd7490e0bd7f47c3ede8752e87625f3e080a4f5224d9191ca455aa56cdfbb` (tag `glm53-local:wheel754421f-dflash2-v2`), one build transferred to all three nodes; export archive `sha256 a7a8d5bd…` |

The pins are machine-readable in [`prep/source-pins.json`](../prep/source-pins.json).

## Checkpoints

| Artifact | Pinned source | Verified |
|---|---|---|
| Target weights | [`turboderp/GLM-5.3-Flash-exl3`](https://huggingface.co/turboderp/GLM-5.3-Flash-exl3) at `2a30229e67012798ba9f0cd832bb78abf4c363d5` (4.05 bpw, 23 shards, 153.8 GiB) | 36/36 files, 167,493,730,166 bytes, SHA-256 against HF LFS metadata on every node ([acquisition](../results/acquisition/)) |
| Draft | [`incoai/GLM-5.3-Flash-DFlash2`](https://huggingface.co/incoai/GLM-5.3-Flash-DFlash2) at `dc77ff1c99eeb2df044ee3d4f0094eb033fee410` (upstream deliberately retained this revision, not HEAD) | same |
| Chat template | [`zai-org/GLM-5.3-Flash`](https://huggingface.co/zai-org/GLM-5.3-Flash) at `690b705278a3a58e538fcb37c2ca8b5f9511213c`, `chat_template.jinja`, SHA-256 `0c4099f3…` | same |

Weights are downloaded by [`prep/download-models.py`](../prep/download-models.py)
against [`download-manifest.json`](../prep/download-manifest.json); nothing is mirrored here.
Acquisition was split across the three nodes and the verified files copied over the QSFP fabric.

## Runtime identity per profile

All profiles share the image, weights, patch tree (`runtime/`, manifest in
[`prep/manifests/prepared-runtime-manifest.json`](../prep/manifests/)), overlay files
(original and patched SHA-256 in `overlay-manifest.json`) and mesh library.

| Profile | Batch tokens | Long-prefill threshold | GPU memory fraction | Video limit | Reported KV pool | Blocks |
|---|---:|---:|---:|---:|---:|---:|
| v1 baseline | 2048 | none | 0.88 | 0 | 7,101,928 | — |
| fair-v2 | 2304 | 256 | 0.88 | 0 | 7,021,917 | 2,563 |
| fair-v3 | 2304 | 256 | 0.80 | 0 | 5,602,739 | 2,045 |
| **fair-v4 (serving)** | 2304 | 256 | 0.80 | 2 | 5,561,643 first boot; 5,657,534 on restart | — |
| scheduler control | 2048 | none | 0.80 | 2 | 5,658,402 | 2,054 |

The per-boot reviewed evidence, produced by
[`prep/collect-runtime-evidence.py`](../prep/collect-runtime-evidence.py) from the
running head container, is under [`results/runtime-evidence/`](../results/runtime-evidence/).

## Test inputs

- Short sweeps: upstream's `bench-sweep.py` protocol, 12 short coding prompts
  ([`prep/hizset-v2.jsonl`](../prep/hizset-v2.jsonl)), 256-token cap, reasoning effort low.
- Correctness probe and 12-task code exam: upstream's, with the generated programs executed in a
  network-less sandbox container rather than on the host.
- Moderate and long-context clients: original synthetic archives with 12 exact-match records per
  archive at 1 to 99 percent depth, plus one generated two-shape PNG per request with an exact
  oracle. Frozen plan SHA-256 `9f85fa0a1f06366db6fecb78ff89cc91c45012b34264461098e4b81cc99b2861`;
  maximum offline text tokens 500,990; the same eight prompts were used for every 500k run. The
  archives themselves are not redistributed (they are large and reproducible from the client's
  `prepare` mode with the pinned tokenizer).
- Video: two 4 s gate fixtures and the test clips, all drawn by
  [`prep/video/make-video-fixtures.py`](../prep/video/make-video-fixtures.py);
  hashes in [`results/video/assets-manifest.json`](../results/video/assets-manifest.json).

## Export policy

[`results/SOURCE_ARTIFACTS.json`](../results/SOURCE_ARTIFACTS.json) lists the SHA-256 of
every original evidence file the public copies were made from. The copies differ from the originals
only where container identifiers or private network identities were removed; every number is
unchanged. Full startup logs (about 700 KB each, dense with host paths) are reduced to their gate,
pool and configuration lines. Model replies are included only for the synthetic video and image
tests, where they are the evidence.

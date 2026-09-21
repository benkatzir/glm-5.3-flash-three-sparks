# GLM-5.3 Flash on three DGX Sparks: eight concurrent 500k-token sessions with vision

A working deployment of GLM-5.3 Flash (EXL3 4.05 bpw, native image and video input, 1M context
limit) across three DGX Sparks joined by three direct QSFP cables, serving eight sessions at once.
It is a **fork and continuation of
[NNNtrance/GLM-5.3-Flash-EXL3-DGX-Spark](https://github.com/NNNtrance/GLM-5.3-Flash-EXL3-DGX-Spark)**
at commit `7f1bd29`: upstream's git history is intact, its README is preserved verbatim as
[UPSTREAM-README.md](UPSTREAM-README.md), and everything added here lives under
[`three-sparks/`](three-sparks/). The kernels, the patch tree, the mesh transport fixes and the
vision arm are upstream's work. Read their README first; it explains the engine.

**What this adds is a measured answer to a question upstream did not test: can the recipe hold
eight independent 500k-token prompts with images at the same time, and what does it take?** It
can. In two runs all eight completed with zero preemptions, every image was answered correctly, and
82 and 84 of 96 exact retrieval checks were correct. The boundary matters as much as the result: first tokens take about
47 minutes, the accuracy figure is one synthetic retrieval run with no comparison against the
unquantized model, and the scheduler change that makes simultaneous decoding possible is a
trade-off, measured here against upstream's settings, not a free win.

## What was measured

Same three machines, same image and weights throughout; temperature 0, reasoning effort low.

| Workload | Streams | Per-stream decode | Result |
|---|---:|---:|---|
| Short coding prompts (upstream's sweep protocol) | 1 | **73.5 tok/s** | 88/88 requests per round passed |
| Short coding prompts | 8 | **28.7 tok/s**, 190.7 aggregate | 97 % of upstream's published [196.1 aggregate](UPSTREAM-README.md#three-nodes--production-configuration-12); TTFT 0.84 s median |
| 8.9k-token prompts, one image each | 8 | own-window 31 to 32 tok/s | 16/16 lookups, 32/32 image fields, 62 s wall |
| **501k-token prompts, one image each (serving profile, fair-v4)** | 8 | **13.08 to 13.60 tok/s**, 107.3 aggregate, in a 235.8 s common window | all eight completed; 84/96 lookups with source record, 32/32 image fields; 0 preemptions; first tokens at 47 min, 52 min wall |
| Same wave on fair-v3 (first completed run, video off) | 8 | 12.85 to 13.64 tok/s, 236.5 s window | 82/96 lookups, 32/32 image fields, 0 preemptions, 52 min wall |
| Same wave, **upstream's scheduler settings** (A/B control) | 8 | 2.2 to 3.0 tok/s for five of the eight | never generated together; first tokens from 6 to 49 min (mean 27 against 47); 79/96 lookups; same 52 min wall |
| Video: one, two, and four-images-plus-two-videos requests; a refused third video; a sub-floor clip; four concurrent videos | 1 to 4 | not a speed test | all correct or correctly refused with the engine alive; one borderline clip flips about 1 in 3 at temperature 0 |

Methods and every per-stream number: [BENCHMARKS.md](three-sparks/docs/BENCHMARKS.md). What none
of this establishes: [LIMITATIONS.md](three-sparks/docs/LIMITATIONS.md). Machine-readable
evidence: [three-sparks/results/](three-sparks/results/README.md).

## The serving recipe

| Component | Setting |
|---|---|
| Hardware | 3 x DGX Spark (GB10, 128 GB unified memory each); three QSFP cables in a triangle, two logical RoCE links per cable |
| Weights | [`turboderp/GLM-5.3-Flash-exl3`](https://huggingface.co/turboderp/GLM-5.3-Flash-exl3) 4.05 bpw at `2a30229e`, vision tower 6-bit EXL3 (99 linears, 0 unquantized) |
| Speculation | [`incoai/GLM-5.3-Flash-DFlash2`](https://huggingface.co/incoai/GLM-5.3-Flash-DFlash2) at `dc77ff1c`, 7 draft tokens, FP8 draft cache (non-commercial licence) |
| Engine | vLLM `0.1.dev20051+g487ecf187` base image at `sha256:905c0293…`, cuda-exl3 `754421f`, upstream's full patch tree, reconstructed serving image `sha256:af1cd749…` |
| Parallelism | TP3 with expert parallelism (96 of 288 routed experts per rank), vision tower data-parallel |
| Transport | nccl-mesh-plugin `19924dcc` plus upstream's three patches, all four RoCE devices per node |
| KV and context | FP8 KV, block size 256, `index_topk` 8192, 1,000,000 tokens per request, 8 sequences; reported pool 5.56 to 5.66M tokens |
| Scheduling | **`--max-num-batched-tokens 2304`, `--long-prefill-token-threshold 256`** (upstream: 2048, none) |
| Memory | **`gpu-memory-utilization 0.80`** (upstream's current production uses 0.88, which left under 2 GiB of free host memory here during eight-way 500k prefill; [why](three-sparks/docs/BENCHMARKS.md#43-why-the-first-attempt-at-upstreams-088-memory-fraction-was-cancelled)), eager mode |
| Multimodal | 4 images and 2 videos per prompt, 8,000-token per-item brake, boot-time video geometry gate armed with fixtures |
| API | OpenAI-compatible on the head, bearer-token middleware on every route except `/health` |

Upstream and this fork side by side, configuration, results and tooling:
[COMPARISON.md](three-sparks/docs/COMPARISON.md). Every difference, with the reason and the evidence:
[DEVIATIONS.md](three-sparks/docs/DEVIATIONS.md).

## Reproducing it

Work through upstream's hardware, fabric and OS documents first ([docs/00](docs/00-hardware-and-os.md)
onwards); nothing here replaces them. Then, on each Spark, with `GLM_ROOT` as the lab directory:

```bash
git clone https://github.com/benkatzir/glm-5.3-flash-three-sparks.git
cd glm-5.3-flash-three-sparks
python3 three-sparks/scripts/verify_sources.py

# 1. weights: pinned, resumable, hash-verified (needs huggingface_hub)
python3 three-sparks/prep/download-models.py --help

# 2. serving image: upstream's Dockerfile was never published; this is a reconstruction
#    pinned base + cuda-exl3 754421f wheel + upstream's DFlash2 port
less three-sparks/prep/bounded-wheel-handoff.md

# 3. mesh transport plugin at 19924dcc + upstream patches 0004-0006
bash three-sparks/prep/build-mesh.sh "$GLM_ROOT"

# 4. runtime tree, overlay, sidecars, per-node env
cp -r three-sparks/runtime "$GLM_ROOT/runtime"
python3 three-sparks/prep/stage-indexer.py --help
python3 three-sparks/prep/make-node-env.py --help      # then append the profile blocks shown in three-sparks/env/

# 5. always dry-run first, then start rank 2, rank 1, rank 0
DRY_RUN=1 ENV_FILE="$GLM_ROOT/private/rank0-fair-v4.env" bash three-sparks/prep/start-private-tp3.sh 0
```

The step-by-step operator view, including profile switching, rollback, the gates to read in the
boot log and how the long-context waves are guarded, is
[OPERATIONS.md](three-sparks/docs/OPERATIONS.md). The preparation notes written before the first
boot are kept as written under [docs/private-notes](three-sparks/docs/private-notes/).

**Nothing here has been rebuilt from a fresh clone on other hardware.** The published files match
the deployed ones by hash; that is a statement about packaging, not portability.

## What this repository contributes

- The first measured eight-way 500k-context result for this recipe, with a client that counts
  returned token IDs against server usage, proves all eight were generating simultaneously from
  scheduler samples, and grades answers strictly ([prep/longvision-c8.py](three-sparks/prep/longvision-c8.py)).
- **A controlled A/B of the one scheduling change**, same prompts, same day, same everything else,
  showing exactly what it buys and what it costs.
- The host-memory finding at 0.88 on these machines, and a guard that cancels a long wave before
  memory pressure becomes an outage ([prep/longvision-memory-guard.py](three-sparks/prep/longvision-memory-guard.py)).
- A reconstruction of the unpublished serving image, CDI GPU access, and an authenticated API in
  place of upstream's open bind.
- Video fixtures so the boot-time geometry gate runs instead of skipping, a CPU replay of the whole
  prelude, a video acceptance battery, and a documented case of temperature-0 non-determinism with
  the input verified identical by hash ([VIDEO.md](three-sparks/docs/VIDEO.md)).

It does not establish accuracy relative to the unquantized model, eight streams at one million
tokens (the pool does not hold them), or that this recipe is better than any other.

## How it was built

Two AI coding agents did the hands-on work under the operator's direction: OpenAI Codex prepared
and executed the deployment through the first long-context retry, and Anthropic's Claude Code took
over mid-run and carried it through video, the A/B and this package. Chronology:
[TIMELINE.md](three-sparks/docs/TIMELINE.md).

## Attribution, licence and evidence policy

Apache-2.0, as upstream. See [NOTICE](NOTICE), upstream's [CREDITS.md](CREDITS.md) and
[LICENSES.md](LICENSES.md), and [PROVENANCE.md](three-sparks/docs/PROVENANCE.md) for every pinned
revision and hash. Model weights are not redistributed. The DFlash2 draft is CC BY-NC-ND 4.0: this
was a personal, non-commercial evaluation.

The public evidence is a copy of the original files with container identifiers and private network
identities removed and no number changed; the SHA-256 of each original is recorded. Credentials,
node addresses, full startup logs and the long-context prompt archives are not included.

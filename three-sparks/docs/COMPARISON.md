# Upstream and this fork, side by side

Upstream is [NNNtrance/GLM-5.3-Flash-EXL3-DGX-Spark](https://github.com/NNNtrance/GLM-5.3-Flash-EXL3-DGX-Spark)
at commit `7f1bd29cf473548212b8b731c52dcf2c7aa5a033`. Upstream's numbers are from its own three
Sparks as it published them; ours are from the three Sparks this deployment ran on. Repository
counts are as of this fork's commit `16ccc58`, the last one before this page was added.

## Repository

| | Upstream `7f1bd29` | This fork |
|---|---|---|
| Commits | 91 | the same 91 plus ours (94 at `16ccc58`) |
| Files | 341 | 571 at `16ccc58`; everything added is under [`three-sparks/`](../README.md) plus the root `README.md` and `NOTICE` |
| Upstream files changed | none | one: upstream's README is kept verbatim as [UPSTREAM-README.md](../../UPSTREAM-README.md) and this fork's README takes its place. `git diff 7f1bd29 -- docs results bench scripts tracks patches` is empty |
| Licence | Apache-2.0 | Apache-2.0, plus a [NOTICE](../../NOTICE) covering third-party components |

## Serving configuration

| Setting | Upstream | This fork |
|---|---|---|
| Weights, draft, base image, kernel revision, patch tree | pinned | identical pins ([PROVENANCE.md](PROVENANCE.md)) |
| Parallelism, KV type, context limit, sequences | TP3 with expert parallelism, FP8, 1M, 8 | identical |
| `--max-num-batched-tokens` | 2048 | **2304** |
| `--long-prefill-token-threshold` | not set | **256** |
| `gpu-memory-utilization` | 0.88 in current production 12 and 13; 0.80 in productions 7 to 9 | **0.80** |
| Reported KV pool | 7,041,322 tokens | 5,561,643 to 5,657,534 tokens |
| Eager mode flag | off in the example file; CUDA graphs end up disabled anyway ([docs/10](../../docs/10-results-and-roofline.md), section 5.8) | on, explicit |
| Images and videos per prompt | 4 and 2 | 4 and 2 (video from profile fair-v4) |
| Boot-time video geometry gate | fixture clips not in the repository, so a fresh deployment skips the gate | fixtures generated and included; the gate runs and passes ([VIDEO.md](VIDEO.md)) |
| Serving image | `docker/Dockerfile.gb10v8`, referenced but not published | reconstructed Dockerfile included ([`prep/Dockerfile.serve-reconstructed`](../prep/Dockerfile.serve-reconstructed)) |
| GPU access | `docker run --gpus all` | CDI device injection; upstream's mode still selectable with `GPU_MODE=legacy` |
| API authentication | none; binds all interfaces | bearer token on every route except `GET/HEAD /health` |
| Fast-load sidecar | yes; boots in about 272 s | none; cold boots in 250 to 260 s |
| Starts at boot | yes, systemd unit | no |

Reasons and evidence for each difference: [DEVIATIONS.md](DEVIATIONS.md).

## Measured results

| Measurement | Upstream | This fork |
|---|---|---|
| Short prompts, 1 stream, aggregate tok/s | 69.7 ([README](../../UPSTREAM-README.md#three-nodes--production-configuration-12)) | 66.1 to 67.8 |
| Short prompts, 8 streams, aggregate tok/s | 196.1 | 190.7 to 192.4 on the fair profiles; 145.0 to 156.1 on the first baseline boot ([BENCHMARKS.md](BENCHMARKS.md) section 1) |
| Correctness probe, code exam | 10/10, 12/12 | 10/10, 12/12, cold and warm |
| Single-stream needle test to 997,952 tokens | 20/20 | not run |
| GSM8K, IFEval, tool-eval-bench, MMLU sample | published ([results/gates](../../results/gates/)) | not run |
| Eight concurrent 501k-token prompts with images, fair settings | not tested | completed twice: 12.9 to 13.6 tok/s per stream with all eight generating together for about 236 s; 82 and 84 of 96 lookups with source record; 32/32 image fields; 0 preemptions; 47 min to first token ([section 4](BENCHMARKS.md)) |
| The same wave on upstream's scheduler settings | not tested | completed once: same 52 min wall; first tokens staggered from 6 to 49 min; five streams decoding at 2.2 to 3.0 tok/s; the eight never generating together; 79 of 96 lookups |
| The same wave at upstream's 0.88 memory fraction | not tested | cancelled at 4 min with the head at 1.8 GiB of free host memory ([section 4.3](BENCHMARKS.md)) |
| Free host memory under load at 0.88, head / worker / worker | 1.86 / 3.52 / 3.48 GiB under a lighter load ([ladder](../../results/memory/ladder-6sep.md)) | 1.83 / 2.79 / 3.79 GiB four minutes into the 500k wave |
| Free host memory under the 500k wave at 0.80 | not tested | never below 10.6 GiB on any node across two runs |
| Video: one, two, and mixed requests; a refused third video | pass ([vision gates](../../results/gates/vision-gates-tp3.md)) | pass on all, plus a sub-floor clip and four concurrent videos |
| Repeatability at temperature 0 | a copy-slip residual is documented | one borderline clip flips about 1 in 3 with the input pixels verified identical by hash |

## Tooling

| | Upstream | This fork adds |
|---|---|---|
| Benchmarks | short sweeps, prefill, throughput stopwatch, quality batteries | an eight-way 500k client that counts returned token IDs against server usage and grades strictly, a moderate eight-way client, and a host-memory guard that cancels a wave before memory pressure becomes an outage |
| Pre-boot checks | a CPU verification script | a replay of the real boot prelude on CPU, including the video gate |
| Launcher | runs directly | a dry-run mode, checked by script on every node before each profile switch |
| Evidence | `results/` | sanitized per-profile evidence with the SHA-256 of each original, a source lock and a verifier |

## Reading the comparison

Upstream's configuration is better tuned for pool size, boot time, and single-stream or queued
work, and it carries far more quality benchmarking. This fork gives up about 20 percent of the pool
and changes two scheduler settings so that eight long sessions make progress together without
starving the host of memory, and it measures that case, which upstream did not test. The scheduler
change is a trade rather than a win; section 4.2 of [BENCHMARKS.md](BENCHMARKS.md) says what it
costs.

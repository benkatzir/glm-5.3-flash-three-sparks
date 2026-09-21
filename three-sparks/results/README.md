# Measured evidence

Every file here is a copy of an evidence file written on the head node during the deployment, with
container identifiers and private network identities removed and nothing else changed. The SHA-256
of each original is in [SOURCE_ARTIFACTS.json](SOURCE_ARTIFACTS.json). No model weights, API keys,
raw startup logs or long-context prompt archives are included. Model replies appear only in the
video and image tests, where the reply is the evidence.

| Directory | Contents |
|---|---|
| `sweeps/` | Short-prompt C1/C2/C4/C6/C8 sweeps: three v1 baseline rounds and one round each on fair-v3 and fair-v4, with the bench log lines. Per-request decode rates use each request's own decode window, 256-token cap |
| `moderate-c8/` | Eight concurrent 8.9k-token requests with images on fair-v2 and fair-v3: strict lookup and image grading, token-ID counts, overlap |
| `long-context-500k-c8/` | The eight-way 500k+image waves: fair-v2 (cancelled for host memory margin), fair-v3 (completed), the scheduler control (upstream batch 2048, no threshold) and the fair-v4 re-run, each with `summary.json`, `execution.json`, the run plan and the memory-guard summary |
| `runtime-evidence/` | Per-profile launch and configuration evidence collected from the running head container: settings, reported pool and block counts, installed-source hashes, no-offload proof |
| `video/` | The four video-test runs on fair-v4, the CPU prelude-replay gate log, and the asset manifests |
| `gates/` | Correctness probe and 12-task code exam (cold and warm), authenticated image probes, GPU RMSNorm gate |
| `mesh/` | Mesh NCCL plugin build qualification, routing and unit-test logs, the applied-source diff, and the three-rank GPU collective probe logs |
| `boot/` | Launch logs per profile, readiness-before-switch receipt, and the gate/pool key lines from each startup log |
| `acquisition/` | Full 36-file checkpoint verification against HF LFS metadata |

## Reading the long-context files

`summary.json` carries, per request, the actual `usage` from the server, whether the prompt
reached 500k tokens, whether the streamed token IDs matched the reported completion count,
time to first generated token, end-to-end seconds, and strict grading (12 lookups per archive,
value and value-plus-record, and four image fields). `common_window` is the longest interval in
which all eight were generating simultaneously with the scheduler reporting eight running and zero
waiting on every sample inside it; per-stream rates there are incremental returned tokens divided
by that window. `concurrency_timeline` records, at each submit and finish event, which requests
were unfinished and which had started generating. `execution.json` has the submit and finish
timestamps in monotonic nanoseconds.

For the scheduler control, `common_window` is absent or degenerate because the eight prompts
never generated together; compare `ttft_generated_seconds` and the per-request
`mean_usage_decode_tps` instead, and read [BENCHMARKS.md](../docs/BENCHMARKS.md) section 4.

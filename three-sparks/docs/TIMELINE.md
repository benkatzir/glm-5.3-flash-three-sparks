# Timeline

All times UTC, 2026. The deployment was driven by two AI coding agents under the operator's
direction: OpenAI Codex prepared and executed the switch from the previous DeepSeek deployment
through the first eight-way 500k retry; Claude Code took over mid-run and carried the work through
video enablement, the scheduler A/B and this package. Private chronology, container IDs and node
addresses are kept out of this file.

| When (Sep 21) | Event |
|---|---|
| 00:24 | Decision: publish the DeepSeek recipe, then move the three Sparks to GLM-5.3 Flash |
| 00:27 to 00:36 | Upstream recipe reviewed against the three-cable topology; missing Dockerfile identified; source package integrity and CPU checks pass |
| 00:38 | Reconstructed serving image builds on a Spark; pinned weights downloading, split across nodes |
| 00:46 | Launcher adapted from `--gpus all` to CDI device injection |
| 01:02 | Mesh NCCL plugin built; routing tests 13/13 |
| 01:12 to 01:29 | All 36 checkpoint files verified on every node; image, plugin and overlay hashes identical across nodes |
| 01:30 | DeepSeek containers stopped and retained; GPU RMSNorm gate and 36-stage three-GPU mesh probe pass |
| 01:37 | v1 baseline serving; pool 7.10M tokens; tower audit 99 EXL3 / 0 BF16 |
| 01:39 to 01:57 | Auth and image gates, correctness 10/10, code exam 12/12 cold and warm, three short sweeps (264/264 requests) |
| 01:59 | fair-v2: batch 2304, long-prefill threshold 256 (still 0.88) |
| 02:05 | Moderate eight-way test (8.9k tokens each, images) 16/16 lookups, 8/8 images |
| 02:07 to 02:12 | First eight-way 500k wave cancelled at 4 min: head under 2 GiB free host memory, no OOM |
| 02:13 to 02:17 | fair-v3: GPU fraction 0.80; pool 5.60M tokens; memory guard written and preflighted |
| 02:20 | Guarded eight-way 500k retry launched |
| 03:01 | Codex session ends mid-monitoring (40 min into the run) |
| 03:12 | Retry completes: all eight answered, 0 preemptions, guard never triggered |
| 05:30 to 05:45 | Claude Code takes over: results recorded, v3 short sweep, health pass |
| 06:10 to 06:20 | Video fixtures generated; full prelude replayed on CPU with the geometry gate passing |
| 06:23 to 06:27 | fair-v4 (video limit 2) launched; gate passes on the real boot; health at 252 s |
| 06:30 to 06:55 | Video battery runs 1 to 4, 30-sample repeat study of the one flaky clip, v4 short sweep |
| 07:00 | Scheduler control profile launched (batch 2048, no threshold, everything else as v4) |
| 07:07 | Same guarded eight-way 500k wave against the control |
| 07:59 | Control completes: same 52 min wall, staggered first tokens, the eight never generate together |
| 08:02 to 08:07 | Control stopped; fair-v4 restored by restarting its retained containers (every patch reports already applied) |
| 08:10 to 09:02 | Same wave re-run on fair-v4: reproduces fair-v3 within 2 percent, 84/96 lookups, memory floor 11.06 GiB |
| after | Package assembled, verified and published |

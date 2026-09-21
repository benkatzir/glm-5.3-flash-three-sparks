# Benchmarks and how to read them

All measurements are from September 21, 2026 (UTC), on three DGX Sparks serving
`turboderp/GLM-5.3-Flash-exl3` at 4.05 bpw with the DFlash2 draft (7 tokens), TP3 plus expert
parallelism, FP8 KV, 1M context limit, 8 sequences, eager mode, temperature 0 and reasoning effort
low unless stated. Profiles are defined in [PROVENANCE.md](PROVENANCE.md). Every number below is
recomputable from the files under [`three-sparks/results/`](../results/).

## 1. Short prompts, one to eight streams

Upstream's sweep protocol: 12 short coding prompts, 256-token cap, per-request decode rate over that
request's own decode window (time to first token excluded), median across requests. Aggregate is
whole-wall. Eighty-eight requests per round, all passed in every round.

| Streams | v1 baseline, three rounds (per-stream tok/s) | fair-v3 | fair-v4 (video on) | fair-v4 aggregate tok/s | fair-v4 median TTFT |
|---:|---|---:|---:|---:|---:|
| 1 | 71.6 (round 1) | 69.9 | **73.5** | 67.8 | 0.285 s |
| 2 | 51.6 | 51.8 | **54.1** | 98.3 | 0.409 s |
| 4 | 39.9 | 40.7 | **40.3** | 131.9 | 0.596 s |
| 6 | 27.6 / 28.3 / 27.6 | 34.0 | **31.8** | 167.6 | 0.727 s |
| 8 | 26.0 / 23.6 / 24.4 | 28.1 | **28.7** | 190.7 | 0.838 s |

Upstream publishes about 28.4 tok/s per stream and 195.8 aggregate at eight streams for the same
protocol on its own hardware; the fair profiles here land on it. Draft acceptance was 60.5 to 66
percent with a mean accepted length of 5.2 to 5.6 throughout. The v1 eight-stream individual range
was 14.1 to 41.4 tok/s. These are short-prompt rates; they say nothing about long context.

Sources: [`results/sweeps/`](../results/sweeps/).

## 2. Functional gates

| Gate | Result |
|---|---|
| Correctness probe (10 machine-checkable questions plus a long paragraph checked for repetition locks) | 10/10 cold, warm, and again on fair-v4; client-visible 9/9; empty content 0 |
| Code exam (12 tasks, generated programs executed in a network-less sandbox container) | 12/12 cold and warm, first attempt; 546 prompt and 862 to 866 completion tokens in total |
| Authenticated image probe (two shapes, left and right) | correct on every profile; 223 prompt tokens |
| Auth gate (no key and invalid key on five routes) | HTTP 401 on all; `/health` alone is public |
| GPU RMSNorm core gate before the first load | max error 0.0 |
| Three-rank mesh collective probe | 36/36 stages with full-tensor assertions, all four RDMA ports active, zero error or discard deltas |

Sources: [`results/gates/`](../results/gates/), [`results/mesh/`](../results/mesh/).

## 3. Eight concurrent 8.9k-token requests with images

Eight independent requests of 8,902 to 8,937 actual prompt tokens, each with one image, two exact
lookups and a four-field image question.

| Profile | Wall | Lookups (value and source record) | Image fields | Natural stops | Token IDs match usage | All eight generating before any finished |
|---|---:|---:|---:|---:|---|---|
| fair-v2 | 80.1 s | 16/16 | 32/32 | 8/8 | yes | yes |
| fair-v3 | 62.4 s | 16/16 | 32/32 | 8/8 | yes | yes |

Source: [`results/moderate-c8/`](../results/moderate-c8/).

## 4. Eight concurrent 500k-token requests with images, and the scheduler A/B

The same eight frozen prompts were used for every run: independent synthetic archives of 501,076 to
501,132 actual prompt tokens (no shared prefix, per-request cache salt), one generated image each,
twelve exact-match records per archive spread from 1 to 99 percent depth, a 4,096-token output cap
with natural EOS allowed. Speeds count returned token IDs checked against the server's completion
usage. A CPU-only client ran on the head with a 90-minute deadline and a host-memory guard on all
three nodes.

### 4.1 The three completed runs

| | fair-v3 | scheduler control | fair-v4 (re-run) |
|---|---:|---:|---:|
| Batch tokens / long-prefill threshold | 2304 / 256 | **2048 / none (upstream)** | 2304 / 256 |
| GPU memory fraction, video limit | 0.80, 0 | 0.80, 2 | 0.80, 2 |
| Reported KV pool | 5,602,739 | 5,658,402 | 5,657,534 |
| All eight completed at 500k or more | yes | yes | yes |
| Total wall | 3,104 s | 3,105 s | 3,091 s |
| Time to first generated token, range | 2,805 to 2,814 s | **354 to 2,946 s** | 2,791 to 2,806 s |
| Mean time to first token | 46.9 min | **27.3 min** | 46.7 min |
| Mean end-to-end per request | 51.4 min | 46.8 min | 51.1 min |
| All eight generating together | **236.5 s window** | **never (0 s)** | **235.8 s window** |
| Per-stream decode in that window | **12.85 to 13.64 tok/s**, 105.8 aggregate | not applicable | **13.08 to 13.60 tok/s**, 107.3 aggregate |
| Per-request own-window decode rate | 13.1 to 13.9 tok/s | **2.2 to 3.0 tok/s for five streams**, then 4.4, 7.4, 23.1 | 12.7 to 14.4 tok/s |
| Preemptions | 0 | 0 | 0 |
| Lookups correct: value / value and record, of 96 | 85 / 82 | 80 / 79 | 86 / 84 |
| Image fields correct, of 32 | 32 | 32 | 32 |
| Output: natural stops, length caps | 7, 1 | 8, 0 | 7, 1 |
| Minimum free host memory, head / worker / worker | 10.64 / 13.01 / 13.22 GiB | 11.72 / 13.89 / 13.95 GiB | 11.06 / 13.21 / 12.99 GiB |

### 4.2 What the A/B shows

The control differs from fair-v4 in exactly two launch settings, upstream's `--max-num-batched-tokens
2048` and no `--long-prefill-token-threshold`, confirmed from the running container's arguments
([runtime evidence](../results/runtime-evidence/scheduler-control.json)).

- **Total time is the same.** Prefilling about four million tokens costs the same 52 minutes
  either way. The fairness settings do not buy throughput.
- **Upstream's scheduler serves the queue in order.** With one prompt consuming the whole batch
  budget, the scheduler admitted a new request roughly every five to six minutes (the metrics showed
  one running and seven waiting for capacity at the start). Early requests therefore get their first
  token much sooner, 6 minutes for the first against 47 for everyone under the fair settings, and
  mean end-to-end latency is about 9 percent lower.
- **But decoding crawls while anyone else is prefilling.** The five requests that started
  generating while later prompts were still being read decoded at 2.2 to 3.0 tok/s over their whole
  answer, because each step's budget was almost entirely prefill. The eight never generated at
  the same time.
- **The fair settings trade first-token latency for simultaneous, usable decode.** All eight wait
  for the collective prefill, then generate together at about 13 tok/s each for four minutes with
  the scheduler reporting eight running and zero waiting on all 233 samples in the window.

Which is better depends on the goal. For a batch of independent jobs where mean latency matters,
upstream's scheduler is the better choice and this recipe's change is a regression. For the
requirement this deployment was built around, several long-context sessions that must all make
progress at a readable rate at the same time, the fair settings are what deliver it. Short-prompt
throughput is unaffected or slightly better at six and eight streams (section 1).

Accuracy with the source record required was 79 of 96 on the control against 82 and 84 on the two
fair runs. The two fair runs used identical settings and identical prompts at temperature 0 and
still differ by two lookups, which puts the noise floor at about the size of the gap to the control
(see [VIDEO.md](VIDEO.md) for a second measured example of that noise). This is not evidence that
scheduling changes answers.

The fair-v4 re-run also reproduces the fair-v3 speed result to within 2 percent (13.08 to 13.60
against 12.85 to 13.64 tok/s per stream, 235.8 against 236.5 s of common window), with video
enabled and a higher host-memory floor.

### 4.3 The cancelled first attempt

The first eight-way wave ran on fair-v2 at upstream's example memory fraction of 0.88 and was
cancelled by the operator after about four minutes: free host memory on the head had fallen to
1.83 to 1.88 GiB in two observations (workers 2.79 and 3.79 GiB), all eight still prefilling, no
OOM, no preemption. It produced no answers and is not a capacity result. Upstream's own memory
ladder records 1.5 to 3.4 GiB free under load at 0.88 and runs its published results at 0.80;
moving to 0.80 cost 1.4M tokens of pool and left more than 10 GiB free on every node through the
entire retry.

Sources: [`results/long-context-500k-c8/`](../results/long-context-500k-c8/).

## 5. Video

See [VIDEO.md](VIDEO.md).

## 6. Boots and pools

Cold load to `/health` 200 took 252 to 261 s on four boots with no fast-load sidecar; restarting a
retained container took 241 s and every prelude patch reported "already applied". The reported KV
pool at the same settings varied between boots (fair-v4: 5,561,643 then 5,657,534 tokens), the same
boot-to-boot spread upstream documents.

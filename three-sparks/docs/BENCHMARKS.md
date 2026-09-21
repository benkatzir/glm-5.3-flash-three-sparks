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

Draft acceptance was 60.5 to 66 percent with a mean accepted length of 5.2 to 5.6 throughout. The v1
eight-stream individual range was 14.1 to 41.4 tok/s. These are short-prompt rates; they say nothing
about long context.

**Against upstream's published numbers.** Upstream's headline for the same protocol on its own three
Sparks (production configuration 12, six rounds over two boots) is **196.1 tok/s aggregate at eight
streams** and **69.7 aggregate / 75.6 per stream at one**
([UPSTREAM-README.md, "Three nodes"](../../UPSTREAM-README.md#three-nodes--production-configuration-12)).
Its per-arm table, which stops at production 7 at the 0.80 fraction, reads 175.1 aggregate and 26.9
per stream at eight ([results/speed/concurrency-sweeps.md](../../results/speed/concurrency-sweeps.md));
its vision promotion gate reads 195.8 aggregate at eight with the tower on
([results/gates/vision-gates-tp3.md](../../results/gates/vision-gates-tp3.md), row K8).

| Eight streams, aggregate tok/s | Value | Share of upstream's 196.1 |
|---|---:|---:|
| upstream, production 12 | 196.1 | 100 % |
| here, fair-v3 | 192.4 | 98 % |
| here, fair-v4 (video on) | 190.7 | 97 % |
| here, v1 baseline, three rounds | 156.1 / 145.0 / 155.9 | 74 to 80 % |

At one stream the fair profiles read 66.1 and 67.8 aggregate (69.9 and 73.5 per stream) against
upstream's 69.7 (75.6), so 95 to 97 percent. An earlier version of this page and of the README said
upstream publishes "about 28.4 tok/s per stream" at eight streams. That figure came from a
preparation note and is not in upstream's files; it has been removed.

The v1 baseline is 20 to 26 percent below upstream at eight streams and the fair profiles are not.
Two things changed between them, the scheduler settings and the age of the kernel tuner cache (v1
was the first boot on these machines, and upstream discards its first rounds as tuner warm-up when
the cache is cold), and no run here separates them. Read the fair numbers as "reproduces upstream",
not as "the scheduler change made short prompts faster".

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

### 4.3 Why the first attempt, at upstream's 0.88 memory fraction, was cancelled

**What happened.** The first eight-way wave ran on fair-v2, which used upstream's current production
memory fraction of 0.88. About four minutes in, with all eight prompts prefilling, zero preemptions
and cache occupancy at only 18 percent, free host memory on the head read 1.83 and then 1.88 GiB;
the workers read 2.79 and 3.79 GiB. At least 43 more minutes of prefill lay ahead. The operator sent
SIGINT to the client, all eight requests were cancelled, and the server drained to zero running and
zero waiting. There was no OOM, no crash and no answer. It is recorded as an unsuccessful
qualification, not as a capacity failure
([cancellation note](../results/long-context-500k-c8/fair-v2-cancellation-note.json)).
The memory guard did not exist yet; it was written because of this run.

**Why free host memory is the thing to watch on a Spark.** The GB10 has one 121.69 GiB pool shared by
the GPU and the operating system. `gpu-memory-utilization` tells vLLM how much of it to claim:

| From the boot logs | 0.88 (v1, fair-v2) | 0.80 (fair-v3, fair-v4) |
|---|---:|---:|
| Claimed by the engine | 107.09 GiB | 97.35 GiB |
| of which weights and non-torch | 55.1 to 55.4 GiB | 55.2 GiB |
| of which peak activation | 1.7 GiB | 1.7 GiB |
| of which KV cache | 50.0 to 50.3 GiB | 40.5 GiB |
| **Left for everything else on the node** | **14.6 GiB** | **24.3 GiB** |

"Everything else" is the kernel, the API server and multimodal frontend on the head (upstream
measured 1.2 to 1.4 GiB for the frontend alone), the three-node mesh transport's buffers, the
tokenized prompts and images of eight half-million-token requests, container runtimes and page cache.
None of it is governed by the fraction, and all of it comes out of the same physical memory. When it
runs out the failure is not a CUDA out-of-memory error on one request. It is the kernel paging or
killing a process on a node that holds a third of the model, which takes down the whole three-node
engine and every session on it.

**Upstream measured the same edge.** Its memory ladder
([results/memory/ladder-6sep.md](../../results/memory/ladder-6sep.md), sections 2 to 4) records minimum
free host memory under load of **1.86 / 3.52 / 3.48 GiB at 0.88** and 1.04 / 1.45 / 1.18 GiB at 0.90,
rejects 0.90 because the head paged 1.5 GB out while every speed number still looked fine, and
describes 0.88 as "the last one before the cliff, with nothing between it and the cliff". Upstream
adopted 0.88 anyway for production 12 and 13 after a stress case of one 1M request, an eight-stream
round and a multimodal request never went below 1.47 GiB
([docs/18](../../docs/18-vision-at-three-ranks.md), sections 8.2 and 9). Its earlier productions, and
the per-arm sweep table, ran at 0.80. Eight simultaneous 500k prefills is a heavier host-side load
than anything on that ladder.

**What the completed runs say the 0.88 wave would have done.** At 0.80 the identical wave was run to
completion twice. The head idled at 12.85 GiB free and bottomed at 10.64 GiB, so the wave itself
costs the head about 2.2 GiB, reached within the first minutes and then flat for the remaining
45 minutes. Moving from 0.80 to 0.88 hands the engine 9.74 GiB more (0.08 of 121.69). Subtracting
that from the measured 0.80 floors gives a projected 0.88 floor of about **0.9 GiB on the head** and
3.3 to 3.5 GiB on the workers. The 1.83 to 1.88 GiB observed four minutes in is consistent with a
run heading there. That projected floor is below the 1.04 GiB at which upstream's own ladder rejected
0.90 for paging.

So the honest reading is: the 0.88 wave was not shown to fail, and by this projection it might have
finished while paging. It was cancelled because at 1.8 GiB and falling, with 43 minutes to go and no
way to know the consumption would plateau, continuing risked a three-node outage for no benefit that
a 9 percent larger KV pool could justify. What consumed the memory was not attributed; the source
review found no workspace that grows with context
([SOURCE_MEMORY_REVIEW.md](private-notes/SOURCE_MEMORY_REVIEW.md)). At 0.80 the pool still holds
eight 520k-token sequences with 276 blocks to spare, and every node kept more than 10 GiB free
through two full runs.

Sources: [`results/long-context-500k-c8/`](../results/long-context-500k-c8/).

## 5. Video

See [VIDEO.md](VIDEO.md).

## 6. Boots and pools

Cold load to `/health` 200 took 252 to 261 s on four boots with no fast-load sidecar; restarting a
retained container took 241 s and every prelude patch reported "already applied". The reported KV
pool at the same settings varied between boots (fair-v4: 5,561,643 then 5,657,534 tokens), the same
boot-to-boot spread upstream documents.

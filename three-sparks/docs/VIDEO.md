# Video on three ranks: turning it on, and what the tests found

Upstream's production configuration 13 serves video, but its repository omits the two fixture clips
that the boot-time video geometry gate reads. On a fresh deployment the gate prints SKIPPED, and
upstream's own history says what a skipped gate can hide: before their VS4 sampler patch, the first
video request killed the engine core on all three ranks. So the first three profiles here served
images only. Profile fair-v4 turns video on, with the gate armed.

## The fixtures and the gate

[`prep/video/make-video-fixtures.py`](../prep/video/make-video-fixtures.py) draws two
deterministic 640x480, 8 fps, 32-frame clips inside the serving image (OpenCV, mp4v): a red square
moving left to right and a blue rectangle moving top to bottom. They live under
[`runtime/fixtures/`](../runtime/fixtures/) with their hashes, because the prelude
reads `$TP3_DIR/fixtures`. Adding them changes upstream's fast-load identity; no sidecar existed
here, so nothing was invalidated.

Before the switch, [`prep/video/run-video-gate-cpu.sh`](../prep/video/run-video-gate-cpu.sh)
replayed the real `tp3-prelude.sh`, same patch order, same env knobs, same read-only overlay mounts,
in a CPU-only container with the final `exec vllm serve` replaced by an echo. The gate passed with
exactly upstream's numbers: both fixtures resolve to grid (4, 36, 46) and 1,656 vision tokens, the
three analytic 1080p cases stay under the 8,000-token brake, and the declared per-prompt video limit
is 2 ([log](../results/video/cpu-prelude-replay-gate.log)). The same lines appear in the
real boot ([key lines](../results/boot/startup-fair-v4-keylines.log)).

## The tests

[`prep/video/video-tests.py`](../prep/video/video-tests.py) mirrors upstream's
K4/K4b/K5/K6 gates and adds a sub-floor clip, a 720p and a 1080p clip, and four concurrent videos.
Temperature 0, reasoning effort low, key read from a file. Four runs on fair-v4; the final run is
[run4-final.json](../results/video/run4-final.json).

| Test | Result |
|---|---|
| one video, each fixture | correct colour, shape and direction every run; 1,713 prompt tokens |
| two videos in one request | both described in order with their difference; 3,406 prompt tokens |
| four images plus two videos | all six items in order, the word ELEPHANT read; 4,293 prompt tokens |
| a third video | HTTP 400 `At most 2 video(s) may be provided in one prompt`, engine alive after |
| a 2-frame, 0.25 s clip (below the sampler floor) | HTTP 400 from the processor, engine alive; never a dead worker |
| 1920x1080, 8 s, 64 frames at the 8,000-token brake | correct every run; 8,017 prompt tokens |
| 1280x720, 8 s, 64 frames, circle rising | flaky, see below |
| four concurrent videos (1.7k to 8k tokens each) | all correct, 18 to 31 s wall |
| still image after the videos; text correctness | correct; 10/10 |

## Two findings

**Empty content under a small output budget.** With reasoning on, 2 of the first 22 video calls
spent the entire 512 or 600 token budget in a verbose frame-by-frame trace and returned empty
`content` with `finish_reason=length`. That is client-visible and worth knowing: give video
requests at least 1,024 output tokens, and treat empty content with `length` as a retry with a
bigger budget. The harness budgets are now 1,024 for one video, 1,536 for two, 2,048 for six items.

**One borderline clip flips at temperature 0.** The 720p 8 s rising-circle clip was called
"stationary" in about one of three identical requests across 30 samples, and more reasoning made
it worse (effort medium: 3 of 6). The engine side was ruled out:

- [`prep/video/pixelhash.py`](../prep/video/pixelhash.py) loaded the clip through
  vLLM's own loader and the checkpoint's processor five times: identical pixel-tensor SHA-256,
  32 delivered frames, the object's centroid rising steadily from y=640 to y=80.
- The mirror-image clip (same geometry, circle descending): 6 of 6 correct.
- A red square moving right at the same size and length: 6 of 6 correct with near-identical token counts.
- The same rising circle in 4 s clips at 720p and 480p: 12 of 12 correct.

So this is the model on a knife-edge input, exposed by the run-to-run numeric noise any
MoE-plus-speculative-decoding engine has at temperature 0. The harness records that clip as
"flaky" rather than as a failure, and the sample data is in
[diag-assets-manifest.json](../results/video/diag-assets-manifest.json) and the run files.

## Cost

Enabling the video limit changed nothing on the decode path: the v4 short sweep reads 28.7 tok/s
per stream at eight streams against 28.1 on v3, and the reported KV pool is 0.7 percent smaller
(5,561,643 against 5,602,739 tokens). The head node's idle free host memory settles about 1 GiB lower
once video traffic has run (encoder activations retained by the allocator).

## Not tested

Long clips at the brake, the brake ladder above 8,000 tokens, any published video benchmark, and
sustained mixed video-plus-text load. Upstream lists the same gaps for its own configuration.

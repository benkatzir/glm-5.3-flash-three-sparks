# Limitations and what is not established

## Accuracy is measured narrowly

- The long-context result is eight synthetic retrieval prompts per run. Strict scoring found 82
  and 84 of 96 lookups correct with the source record on the two fair runs (85 and 86 on value
  alone), and 79 of 96 on the scheduler control. That is a needle-style retrieval task with exact-match grading, not a
  reading-comprehension or reasoning benchmark, and each configuration was run once.
- **No comparison against the unquantized model exists.** Every file in this repository records
  `general_or_native_relative_accuracy_claimed: false`. The 4.05 bpw EXL3 checkpoint, the 6-bit
  vision tower, FP8 KV, `index_topk` 8192 and speculative decoding are all in the path, and nothing
  here isolates what any of them costs. Upstream reports GSM8K, IFEval and tool-eval figures for
  its own configuration; none were re-run here.
- The 10-question correctness probe and the 12-task code exam are functional gates that catch a
  broken engine. They are not accuracy estimates.
- Image and video tests use synthetic shapes and one rendered word. They prove the tower is
  loaded and bound correctly, not that visual understanding matches any baseline.

## Outputs are not bit-reproducible at temperature 0

Identical requests can return different text. On most inputs the answer is stable to the token
count; on one borderline video clip about a third of 30 identical requests flipped between two
answers, with the input pixels verified identical by hash. A single pass or fail on any one prompt
therefore means less than it looks, and the three-lookup difference between the two 500k schedulers
should be read in that light.

## Long-context latency is long

Eight 500k prompts take about 47 minutes before the first generated token under the fair settings,
and 52 minutes end to end. Decode with eight 500k contexts resident is about 13 tok/s per stream,
roughly half the short-prompt rate. One to seven streams at 500k, and any context length between
9k and 500k, were not measured.

## Eight streams at one million tokens do not fit

The model limit is configured at 1M per request, but the reported pool is 5.56 to 5.66M tokens at
the 0.80 memory fraction, and eight 1M requests need more than 8M. Five streams at 1M, or eight at
roughly 650k, fit by the block arithmetic; neither was run. Upstream's single-stream 1M needle test
was not repeated here.

## The scheduler change is a trade, not a win

Section 4 of [BENCHMARKS.md](BENCHMARKS.md): the fair-prefill settings cost early requests 20
minutes of first-token latency on average and about 9 percent of mean end-to-end latency in exchange
for simultaneous decode at a usable rate. For queue-style batch work upstream's settings are better.

## Reproduction gaps

- There is no completed 500k run at fully original settings (upstream's scheduler together with its
  0.88 memory fraction). The 0.88 attempt was cancelled at four minutes, and the scheduler control
  ran at 0.80. What the unmodified recipe does at eight-way 500k on these machines is therefore a
  projection ([BENCHMARKS.md](BENCHMARKS.md) section 4.3), not a measurement.

- The serving image was **reconstructed**: upstream's Dockerfile was not published. The image here
  builds and passes every gate, but it is not upstream's image and no sidecar or byte comparison
  against upstream's exists.
- Nothing in this repository has been rebuilt from a fresh clone on different hardware. The
  published files match the deployed ones by hash ([`source-lock.json`](../source-lock.json)),
  which is a statement about packaging, not about portability. Interface names, fabric addressing
  and free-memory behaviour are specific to these three machines.
- No fast-load sidecar was produced, so boots are cold loads.
- CUDA graphs are off, as on upstream's measured configurations.
- No profile starts at boot.

## Video

Clips longer than eight seconds, more than 8,000 vision tokens per item, sustained mixed
video-and-text load, and any public video benchmark are untested. Reasoning can consume a small
output budget on video requests and return empty content; see [VIDEO.md](VIDEO.md).

## Licensing constraint

The DFlash2 draft model is CC BY-NC-ND 4.0. This was a personal, non-commercial evaluation. Serving
commercially requires replacing or removing the draft, which changes every speed number here.

# Private GLM eight-stream long-context qualification

This client is prepared for the three-Spark GLM deployment. Its local synthetic
checks pass; no requests or GPU tests were run while preparing it. It changes no
serving configuration. Run it only after the normal short text/vision gates and
the current runtime's capacity check pass.

## Inputs and preparation

`longvision-c8.py prepare` makes eight independent random archives, each containing
500,000–505,000 text tokens according to the exact pinned target tokenizer. Each
archive contains 12 unique exact-match records distributed from approximately 1%
to 99% depth. The query asks for their values and record IDs. The independent PNGs
contain two colored shapes with an exact image oracle. These are original generated
fixtures, not borrowed datasets or images.

All eight archives differ throughout; they do not reuse a common filler prefix.
Each request also has its own cache salt. The full request, image, oracle, tokenizer
identity, fact locations and input hashes are frozen in the preparation directory.
The actual serving usage, not the offline estimate, decides the 500k criterion.

The client needs the serving environment's `tokenizers` package for preparation and
`httpx` for the run. There are no model imports. Use the pinned image's Python in a
CPU-only helper container if those packages are unavailable on the head. Mount the
script, manifest, target tokenizer, and private output directory; do not request a
GPU. All paths below are examples and should be set to the existing head paths:

```bash
umask 077
TASK_DIR=/path/to/glm53-three-sparks
DATA_DIR=/path/to/glm53-data
QUAL_DIR=/path/to/private/glm-c8-qualification
PYTHON=/path/to/python-with-tokenizers-and-httpx

"$PYTHON" "$TASK_DIR/longvision-c8.py" prepare \
  --tokenizer "$DATA_DIR/models/target/tokenizer.json" \
  --download-manifest "$TASK_DIR/download-manifest.json" \
  --model glm-5.3-flash \
  --max-tokens 2048 \
  --output "$QUAL_DIR/prepared"
```

The default served model is the actual full deployment's `glm-5.3-flash`, rather
than the upstream launcher's fallback alias. Preparation rejects a different
tokenizer or original download manifest. Review `prepared/plan.json` before use.
Preparation/output directories must be fresh; the tool will not overwrite them.

Each answer starts with the retrieval/image JSON, followed by a substantial benign
archive-service engineering task. The 2,048-token cap targets a useful generation
interval while permitting EOS normally. It does not force meaningless generation.
Optional preparation caps are 3,072 or 4,096. They do not guarantee a long overlap:
the model may finish naturally, or the scheduler may complete early requests while
later prompts are still prefilling. The test reports what happened.

## Runtime evidence and execution

Before the wave, save `runtime-evidence.json` as a JSON object containing the
current image/source identity, full relevant scheduler/parallelism/KV settings,
actual cache block count and capacity, no-offload configuration, and hashes/paths
of the startup evidence. Confirm capacity accommodates all eight prepared prompts,
vision/template overhead and output budgets. The client copies and hashes this
evidence; it does not inspect devices or infer an allocation size from config alone.

Keep the current baseline unchanged for its first qualification. Run from the head
against its loopback API with the existing restricted key file. The client refuses
a non-loopback URL, insecure key permissions, or an API that cannot be observed
idle through authenticated `/metrics` immediately before the wave. No other client
should submit requests during this isolated qualification.

```bash
"$PYTHON" "$TASK_DIR/longvision-c8.py" run \
  --prepared "$QUAL_DIR/prepared" \
  --output "$QUAL_DIR/run-01" \
  --url http://127.0.0.1:8888 \
  --key-file /path/to/existing/private-api-key \
  --runtime-evidence "$QUAL_DIR/runtime-evidence.json" \
  --deadline-seconds 5400
```

The 90-minute deadline bounds the wave including its prefill. HTTP streams are
closed on timeout or interruption; check server running/waiting counts return to
zero afterward. A deadline is reported as a canceled qualification, not as a proven
capacity failure. Client errors and incomplete streams exit nonzero. A completed
wave may still fail content or overlap criteria; inspect `summary.json`.

## What is measured

The client requests `return_token_ids=true`, cumulative continuous usage, and final
usage. Per-request token-ID totals must exactly match actual completion usage for
the exact common-window speed result. A usage-only final SSE event is handled.
Prompt token IDs returned in a top-level field are preserved privately but never
counted as generated tokens. Neither SSE event count nor retokenization is used as
a token-count substitute.

- **Own decode mean:** actual final completion usage divided by that request's
  first-to-last generated-token receipt interval, including its first token. This
  is clearly labeled as each stream's own interval.
- **Common decode interval:** latest first-generation receipt to earliest
  last-generation receipt. Returned token-ID increments within that interval give
  per-stream and aggregate rates. Rates are client-observed and include generation
  in reasoning and content; content and reasoning are also saved separately.
- **TTFT and elapsed time:** generated-token TTFT, visible-content TTFT, and each
  request's total elapsed time are separate.
- **Concurrency:** a timeline distinguishes submitted unfinished requests from
  requests that have started generation. Authenticated metrics are sampled about
  once per second, preserving the raw series and labels.

`observed8way60second_processed_context_window` requires all eight completed
requests to report at least 500,000 actual prompt tokens, every request to start
generation before any request finishes, matching actual token counts, at least
60 seconds of common generation, running=8/waiting=0 throughout the sampled common
window, no observed preemption-counter increase, and telemetry coverage near both
boundaries without gaps longer than three seconds. Together with the reviewed
no-offload runtime evidence, this corroborates eight simultaneously processed
contexts. Eight submitted HTTP requests alone does not meet the criterion.

## Content grading and retained evidence

Each exact lookup receives separate value and value-plus-record scores. Image
grading reports all four fields and the full exact object, with an additional
case/whitespace-normalized field diagnostic. JSON must begin the final content for
the strict parse result. A separate diagnostic can recover a single unambiguous
embedded or fenced object; conflicting candidate objects are never cherry-picked.
Strict scores remain distinct from these diagnostics. Reasoning text is retained
but is not substituted for a missing final answer.

Each run retains request copies, normalized SSE payload records, per-event token
IDs and receipt times, final usage/finish reasons, delivered content and reasoning,
HTTP error bodies where available, metrics, runtime provenance, and the summary.
The `.sse` file preserves SSE data payloads with normalized framing, not an exact
wire-byte capture. These artifacts remain private; they include full prompts,
model output and host/runtime details. Returned prompt token IDs increase raw-log
size and client parsing work, so leave adequate host memory and disk headroom.

Regrade without replacing the original summary:

```bash
"$PYTHON" "$TASK_DIR/longvision-c8.py" grade \
  --prepared "$QUAL_DIR/prepared" --results "$QUAL_DIR/run-01" \
  --output-summary "$QUAL_DIR/run-01/regrade-01.json"
```

This is a bounded synthetic retrieval/vision and serving-concurrency qualification.
It does not establish broad benchmark accuracy or a percentage of native quality.

## Optional later fair-prefill qualification

The pinned vLLM V1 scheduler at `487ecf187` has
`long_prefill_token_threshold`, but does not have the old
`max_num_partial_prefills` / `max_long_partial_prefills` policy knobs. A threshold
of zero does not cap each long request's per-step prefill allocation. The observed
baseline uses 2,048 for both `max_num_batched_tokens` and
`max_num_scheduled_tokens`; startup warns that draft slots need additional input
budget. Leave that baseline unchanged for the first run.

If the baseline produces insufficient overlap, separately review an optional
`--long-prefill-token-threshold 256 --max-num-batched-tokens 2304` qualification.
This is a proposal, not an applied or tested setting. Verify the actual draft-slot
count, `max_num_scheduled_tokens`, Mamba alignment behavior, encoder budget and
cache capacity in the resulting config before running it. The intent is eight
256-token prefill slices plus room for draft slots. It is fairer interleaving, not
a prefill barrier; it can still yield insufficient overlap. Keep that run's config
and results distinct from the pinned baseline.

Pinned primary source references:

- [Scheduler config](https://github.com/vllm-project/vllm/blob/487ecf187/vllm/config/scheduler.py)
- [V1 scheduler and draft-slot input accounting](https://github.com/vllm-project/vllm/blob/487ecf187/vllm/v1/core/sched/scheduler.py)
- [Chat streaming protocol](https://github.com/vllm-project/vllm/blob/487ecf187/vllm/entrypoints/openai/chat_completion/protocol.py)
- [Streaming token IDs and cumulative usage implementation](https://github.com/vllm-project/vllm/blob/487ecf187/vllm/entrypoints/openai/chat_completion/serving.py)

Offline checks: `python3 test-longvision-c8.py`. The four test groups cover original
PNG structure/uniqueness, strict versus diagnostic grading, exact interval rates
and false-pass guards, and an in-process fake SSE stream with prompt IDs and a
usage-only final event. They make no network requests and do not validate the model.

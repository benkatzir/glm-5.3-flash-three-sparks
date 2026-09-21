# Moderate C8 and large-image protocol check

`moderate-c8.py` is local preparation, not a model qualification result. It uses
stdlib HTTP and imports sibling `longvision-c8.py` for hashes, metric parsing and
strict/diagnostic grading. Only offline `prepare` requires `tokenizers`, from the
pinned serving environment. No model imports or GPU requests are needed to prepare.

Preparation pins the original download manifest and target tokenizer. It creates
eight unrelated 8,000–8,500 text-token archives, two exact records per archive at
roughly 20% and 80% depth, and eight original 1024×512 PNGs generated directly from
pixel geometry. No image is resized. Each image has a left and right colored shape.
Pixel dimensions are recorded; image-token counts are not assumed from dimensions.

```bash
python3 moderate-c8.py prepare \
  --tokenizer /path/to/data/models/target/tokenizer.json \
  --output /path/to/private/moderate-prepared
```

Default model: `glm-5.3-flash`. The wave uses native low reasoning, clear thinking,
natural EOS, a 256-token output cap, continuous actual usage and returned token IDs.
The runtime profile is never altered by this client.

First compare an image-only request with the identical text-only request, using the
same chat settings. This is a separate live invocation, not part of preparation:

```bash
python3 moderate-c8.py image-probe \
  --image /path/to/private/moderate-prepared/case-00/image.png \
  --key-file /path/to/existing/private-api-key \
  --output /path/to/private/moderate-large-image-pair \
  --url http://127.0.0.1:8888 --deadline-seconds 600
```

The summary reports actual prompt usage for both requests and their difference.
`image_input_prompt_token_increase` includes image template markers along with the
image's tokens. It is not inferred from the image request's total prompt length.
Explicit `prompt_tokens_details.image_tokens`, if returned, is reported separately.
Use the paired delta or the pinned processor to verify that the large image takes
more than a 256-token prefill slice; do not claim an exact visual-token count from
the delta alone. Both full request/response artifacts are retained for inspection.

Then run the eight prepared requests together from the head:

```bash
python3 moderate-c8.py run \
  --prepared /path/to/private/moderate-prepared \
  --key-file /path/to/existing/private-api-key \
  --output /path/to/private/moderate-c8-run \
  --url http://127.0.0.1:8888 --deadline-seconds 1800
```

The wave requires observed running=0/waiting=0 before submission. Each stream saves
its frozen request, normalized SSE payloads, exact token-ID events/timestamps,
actual usage, final reason, visible content, reasoning, and HTTP error body if any.
Prompt token IDs are not counted as generated tokens. Token-ID totals must match
actual completion usage. The strict score checks both exact values and record IDs,
plus all left/right image fields. Embedded JSON and case/whitespace image results
are separate diagnostics, preserving strict failures.

Exit 0 requires all eight complete, report at least 8,000 actual prompt tokens,
match generated counts, return every strict fact/image answer, finish naturally,
and start generation before any request finishes. A length-limited or malformed
answer remains a failed result; the script does not increase the cap or retry.
Exit 1 denotes incomplete/protocol failures; exit 2 denotes a completed wave that
missed a functional/overlap gate. Examine individual results even when it fails.

The hard deadline is 60–1,800 seconds. On expiration, a watchdog writes
`deadline.json` and exits 124; flushed partial SSE/event artifacts remain. Verify
server queues return to zero after a canceled wave. All directories must be fresh,
are private, and are never overwritten. Keys are loaded from restricted files,
never printed, and sent only to the loopback API with proxies/redirects disabled.

Per-stream speed is actual completion usage divided by its own first-to-last
generated-token receipt interval. This moderate functional test makes no sustained
common-window speed, 500k capacity, or general/native-relative quality claim.

Local-only validation passed: Python syntax, eight unique original 1024×512 PNGs,
and an in-process fake SSE response verifying reasoning/content capture, prompt-ID
exclusion, actual usage equality, and the empty-choice final usage event. No API,
SSH, tokenizer checkpoint preparation, or GPU calls were made during implementation.

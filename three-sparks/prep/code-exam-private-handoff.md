# Private GLM code exam handoff

Ready for root to transfer and run on the head. No SSH, Docker, HTTP request, generated program or GPU work was performed while preparing this adaptation. Eight local mocked checks passed.

Files:

- `code-exam-private.py` — standalone Python standard-library client and Docker runner.
- `test-code-exam-private.py` — local mocked verification, never runs Docker/API/candidate code.

Run after the private GLM API is healthy and authenticated:

```bash
sudo python3 /home/ben/glm53-lab/prep/code-exam-private.py \
  --base http://127.0.0.1:8888 \
  --api-key-file /home/ben/glm53-lab/private/api-key \
  --out /home/ben/glm53-lab/code-exam-round1.json \
  --repeats 1
```

Use a fresh result filename for each run. Results are written mode0600. Exit0 means every original assertion suite passed; exit1 means at least one generation/execution failure; exit2 means setup failure. Every task/repeat runs even if another fails. This is a12-task functional gate, not a model-level accuracy measurement.

The default sandbox image is the already pinned base:
`vllm/vllm-openai@sha256:905c02933be6021301db2dc284e24e3727467aa3a0f63b41d609885778a07bce`.
The script inspects the local image, refuses declared automatic volumes, then uses its immutable image ID with `--pull=never`. It never pulls/builds an image. If an equivalent already-local image must be selected explicitly, `--sandbox-image` accepts only a full immutable digest/image ID. The Docker client is forced to the local Unix socket with a minimal environment.

Each generated candidate plus the unchanged original assertions reaches `python3 -I -S -B -u -` through stdin. The only container mounts requested are an ephemeral16MiB `/tmp` tmpfs; there are no host bind mounts, named volumes, API keys or GPU devices. The root filesystem is read-only, networking is disabled, runtime is runc, user65534, capabilities are dropped, privilege escalation is disabled, and the image environment is cleared before Python starts. Limits:256MiB memory including swap,1CPU,32PIDs,20CPU seconds,25s wall time, bounded output. The client always force-removes its uniquely named owned container, including timeout/error paths. Container cleanup failure counts as a failed attempt. The API call has the unchanged600s timeout, separate from the25s candidate runtime limit.

All12 prompts/assertion suites match upstream `scripts/code-exam.py` at7f1bd29cf473548212b8b731c52dcf2c7aa5a033. Generation settings remain temperature0, max_tokens1600, thinking enabled, low reasoning effort. Content-to-reasoning fallback and fenced-code extraction are preserved. A pass now requires exit0 and the post-assertion completion marker; merely printing DONE does not override a failed assertion/nonzero exit.

Bearer auth is added only to the host's inference request, with proxies disabled and redirects refused. Key content is not placed in a command, container environment, result or terminal output. Per-attempt actual response usage, nested usage details, finish reason, request time, source hash and execution outcome are recorded. Aggregates sum only present numeric usage counters and show how many attempts reported each; missing usage is not replaced with an estimate or zero.

Verification performed locally:

```bash
python3 work/glm53-three-sparks/test-code-exam-private.py
```

Eight tests PASS: original12-task equality; isolation/resource command construction and stdin-only source; nonzero exit despite completion marker; timeout and owned-container cleanup; cleanup failure; absent local image without pulling; host Bearer auth and unchanged request settings/actual usage; all12 failure outcomes with missing-usage accounting and nonzero exit. No generated code was executed in these tests.

SHA256:

- code-exam-private.py: `5fe044b4988df1d861312edd82b941b3628e84604856f6bcf6969341814a8149`
- test-code-exam-private.py: `75d32bd0e32de00ac095485efca3d4df6a87c26b8c966b7ad72e532661ca43d9`

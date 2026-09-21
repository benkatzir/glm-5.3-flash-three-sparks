# GLM-5.3 Flash on three Sparks: deployment preparation

Prepared locally on 2026-09-20. **Updated executable handoff: [private-handoff.md](private-handoff.md)**. The private handoff supersedes the remaining-work notes below for overlay staging, launcher/auth, image-only fixtures, and download/client wrappers. No SSH, node changes, Docker builds, model downloads, inference calls, or engine stops were performed by this preparation task. Root owns deployment, secrets, and publication order. Preserve the current DeepSeek result bundle and rollback before replacing its runtime.

## Selected source and topology

- Recipe: `upstream/`, clean clone of `NNNtrance/GLM-5.3-Flash-EXL3-DGX-Spark` at **7f1bd29cf473548212b8b731c52dcf2c7aa5a033**. No AGENTS.md exists in that checkout.
- Kernel source: `cuda-exl3/`, detached at **754421fc99919317b9a4cf2928797bae8f870040**. No AGENTS.md exists at that revision.
- Exact upstream target/draft/template/base pins are in `source-pins.json`.
- **Three physical QSFP cables are the correct topology.** `docs/00-hardware-and-os.md` §4 explicitly corrects the older use of “two cables per pair”: each physical cable carries two logical RoCE links, on different PCI endpoints. There are three cables, six links, four RoCE devices per node. No extra cables are required by this recipe.
- Upstream directed ring: head Port0 → worker1 Port1; worker1 Port0 → worker2 Port1; worker2 Port0 → head Port1. Port0 is next to Ethernet. Verify actual existing LLDP/interface mapping rather than recabling by assumption.
- Preserve the user's working fabric addresses. Verify both logical links per pair using bound pings, four PORT_ACTIVE devices per node, and later transmit-counter deltas on all four. Use management address/interface for rendezvous and Gloo. Mesh plugin handles the separate fabric subnets; do not substitute stock NCCL IB settings from a two-node recipe.
- With verified dual logical links, upstream uses `NCCL_MESH_LINKS_PER_PEER=0` (auto/all), `NCCL_MAX_NCHANNELS=8`, `NCCL_MESH_PTR_CUDA=1`, `NCCL_MESH_FLUSH=1`, and `NCCL_MESH_MIN_RNR_TIMER=1`. If only one logical link actually works, `LINKS_PER_PEER=1` is an adaptation, not the published performance configuration.

## Acquisition and storage

Use HF `download --revision` with the full revisions below, record per-file SHA256 against HF LFS metadata, and copy verified files over the existing fabric. No fallback checkpoint is needed.

| Artifact | Pinned source | Approximate storage |
|---|---|---|
| Target | `turboderp/GLM-5.3-Flash-exl3` @ `2a30229e67012798ba9f0cd832bb78abf4c363d5` | 165 GB /153.8 GiB, 23 weight shards |
| Draft | `incoai/GLM-5.3-Flash-DFlash2` @ `dc77ff1c99eeb2df044ee3d4f0094eb033fee410` | 2.34 GB BF16 |
| Chat template | `zai-org/GLM-5.3-Flash` @ `690b705278a3a58e538fcb37c2ca8b5f9511213c`, `chat_template.jinja` | 10,950 bytes |
| Base image | `vllm/vllm-openai@sha256:905c02933be6021301db2dc284e24e3727467aa3a0f63b41d609885778a07bce` | ~31 GB |
| Fast-load sidecar | Produced locally after all patches/config are final | ~53 GB per rank |

Target and draft padding sidecars are symlink trees, not second weight copies. Budget roughly **250 GB per node** for one local checkpoint, draft, shared Docker layers, and one fast-load sidecar, plus build cache/logs and the retained DeepSeek rollback. Check actual free disk and Docker layer sharing before acquisition. Avoid exporting a new NFS service merely to save this space unless local disk requires it.

The latest draft HEAD is `bf582e4e…`; upstream explicitly retained **dc77ff1c**, so do not accidentally download HEAD. The template SHA256 is `0c4099f3382d6c92700dfb99725025360966fd73032f0ecf32377c0d9e6309c5`; run `scripts/verify-chat-template.py` against the downloaded file.

Licenses: recipe Apache-2.0; selected target and base model MIT; cuda-exl3 MIT; draft CC BY-NC-ND4.0. Personal noncommercial evaluation is the planned use. Do not publish modified draft weights or assume the recipe author's separate permission applies to commercial serving. Upstream's container redistribution claims are its interpretation, not a legal review; we only need local builds here.

## Image build: material reproducibility gap and prepared fallback

Upstream docs/02 still describes historical `f4987cf` in several commands, but this full-scope TP3 target **requires754421f**. More importantly, the required `docker/Dockerfile.gb10v8` is untracked and absent from both repositories. Exact replay of the author's original Dockerfile is impossible from these published files alone.

`Dockerfile.serve-reconstructed` is a minimal, explicitly labeled reconstruction from the kernel repository's tracked `docker/Dockerfile.sparse-mla`: pinned base, `TORCH_CUDA_ARCH_LIST=12.1`, `MAX_JOBS=3`, no dependency replacement, and a compiled-extension import gate. It is **not built or validated**. Keep a distinct image tag and record this adaptation in our runtime identity.

On an ARM64 Spark, after the required publication/rollback and resource checks, the build shape is:

```bash
docker build --memory=4g -f /path/to/Dockerfile.serve-reconstructed \
  -t glm53-local:serve-754421f /path/to/cuda-exl3
docker build --memory=4g --build-arg BASE=glm53-local:serve-754421f \
  -t glm53-local:754421f-dflash2 /path/to/upstream/patches/dflash2-port
```

Use the pinned kernel source as the first context. Keep source/build logs and actual image IDs. One build transferred to all three produces identical artifacts; independent builds may differ because upstream documented NVCC nondeterminism. Either way, record identity **and** run behavior checks. Verify `cuda_exl3._C`, expected vLLM `0.1.dev20051+g487ecf187`, `/opt/harem/dflash2-gate.py`, `check-padload-tp3.py`, and the pinned upstream tests. The older published suite count44passed/41skipped is a reference; record the actual count at754421f rather than forcing it.

Build `autoscriptlabs/nccl-mesh-plugin` at short revision19924dcc plus recipe patches0004,0005,0006 in a separate directory. Resolve its full commit before building; run its unit test and retain the resulting library under a GLM-specific path. Reusing an existing mesh library is valid only if its source/patch identity matches. No host kernel or network reconfiguration is inherent in these userspace builds.

## Prepared runtime tree and remaining assembly

`prepare-local-tree.py` already created **prepared-runtime-7f1bd29/** without modifying upstream. It flattens the workspace, prefix-hit, K-pool tail, FlashKDA, fail-closed parser, and XGrammar scripts into the directory expected by the prelude; inserts the missing XGrammar invocation and vision hook; and hard-links `tp3-prelude.sh` to `tp3full-prelude.sh`. Shell syntax, Python parsing, and all named prelude file references pass. Hash manifest: `prepared-runtime-manifest.json`. These are source-only checks, not image compatibility evidence.

Remaining before launching:

1. **Extract the two sparse-indexer Python files from the pinned image** into a GLM-specific overlay directory. Apply `patches/indexer-overlay/0001…diff` and0002 to those copies. Pre-apply K-pool initialization and workspace-bound modifications before read-only mounting; the patch scripts also modify other vLLM files, so stage a temporary copy of the necessary package paths and then copy back only the two overlay files. Do not let a boot attempt write to its read-only bind mount.
2. **Vision MP4 fixtures are missing from the published repository.** The geometry gate requires at least one `.mp4` and the prelude otherwise skips it if `fixtures/` is absent. Generate small, deterministic ≥4-second clips in `prepared-runtime-7f1bd29/fixtures/` (e.g. horizontal red shape and vertical blue shape, distinct temporal directions), hash them, and run the real processor geometry gate. Do not represent “SKIPPED” as a pass. The existing `verify-cpu.sh` predates some later patch registrations; additionally execute the actual final prelude patch order in a throwaway container before serving.
3. Generate target sidecar with `pad-tp3full.py SOURCE DEST --tp 3`; draft with `pad-tp3.py SOURCE DEST --tp 3 --draft`. Source directories are never modified. Mount both sidecars and their link targets at the same absolute host/container paths so relative links resolve.
4. Derive separate private per-rank env files from `tracks/tp3/env.tp3-full.example`, with current node addresses and paths. No live env or secret template was created by this task. Set a unique `NAME` and port, and preserve existing DeepSeek container/config names.

## Serving choices and template traps

Recommended first reproduction: TP3, EP on (96 of288 routed experts per rank), full-scope4.05bpw target, native routed top-k unchanged, DFlash2 seven draft tokens, target/draft FP8 KV,1,000,000 max context,8 max sequences,2048 batched tokens,256 block sizes, vision tower on and data-parallel replicated, `reasoning_effort=low`, `clear_thinking=true`, `index_topk=8192` as latest upstream recipe.

- **Set `ENFORCE_EAGER=1`.** Current example says0 although the cited current production configuration is eager; do not quietly introduce an unqualified graph mode.
- First load: `FASTLOAD_MODE=` empty. The example says`load` and points to a nonexistent/old sidecar. Once the complete stack passes, take a fresh uniquely named `dump`, then `load`; never overwrite a rollback sidecar. Prelude, file-set, checkpoint, template/config/override changes must be bound to the new runtime.
- The recipe's0.88 memory fraction is measured on ASUS GX10 and leaves little host headroom. Match deliberately only after full memory settles and ongoing all-node telemetry is available. A lower initial fraction is an explicit memory adaptation; record its actual token pool. The launcher's settle loop **does not fail** if112GiB is not reached—root should gate this externally rather than accept its printed warning.
- Keep `HAREM_XGRAMMAR_BACKPORT=1` explicitly alongside the example's other gates. Setting it alone is insufficient without the inserted prelude call; the prepared tree supplies that call.
- `EXTRA_ENV` and `EXTRA_ARGS` are word-split. JSON must remain compact; paths must not contain spaces. `--hf-overrides` is one object with quantization config path and `index_topk`.
- Vision limits:4images/2videos, `max_pixels=12544000`, `max_image_tokens=8000`, MM processor cache0. The8k-per-item brake matters for video memory. Keep the6-bit EXL3 tower loader audit99EXL3/0BF16.
- Do not copy firmware updates, reboot policies, sysctl changes or hotplug changes from the upstream quick-start as prerequisites on already-repaired hardware. Inspect actual state first; those docs describe ASUS firmware, not necessarily our NVIDIA units.

## Authentication and verification

The upstream launcher binds `0.0.0.0` without auth. Our private launcher now defaults to loopback, supports explicit LAN binding, and mounts an all-route ASGI auth module (GET/HEAD `/health` alone is public). The key stays in a private file: built-in `VLLM_API_KEY` is deliberately unset because its coverage is incomplete and redundant environment exposure is unnecessary. The key-free CPU auth tests pass; real HTTP401 and authorized-inference probes are provided. See `private-handoff.md` for exact commands and the CDI GPU request matching the actual nodes.

Start rank2,rank1,then rank0 only after all three previous inference ranks are stopped and memory settles. Avoid systemd/autostart until this manual launch passes. Required checks in order:

1. Health and identity: all three alive, correct image/source pins, full-scope anchors, pad audit, workspace bound, no unexpected BF16 fallback, FlashKDA/parser/XGrammar markers, final startup config summarized without secrets.
2. Short quality: upstream correctness probe10/10 and code exam12/12, cold and warm. **Code exam executes generated Python without a sandbox**; run its generated programs in an isolated container with no network or host mounts, not directly on the Mac/host. Preserve its tasks/scoring. Add auth to a copy of clients or use a loopback auth-injecting proxy.
3. Vision: explicit image recognition/OCR and multiimage identity checks; video geometry and limits if video support is advertised. Correct answers are required, not simply HTTP200.
4. Concurrency: reproduce upstream short coding C1,C2,C4,C6,C8 with at least three warmed rounds and actual usage token counts. `bench-sweep.py` reports **median per-request decode**, excludes TTFT from it, repeats12prompts, and its aggregate includes whole-wall time. Missing usage currently falls back to SSE chunk count—reject such observations rather than count chunks as tokens. Keep prose in a separate panel.
5. Long-context: independently salted prompts, actual token counts; prove500k first on one request, then six, then eight with images and substantive scored answers. Record all-stream overlap and≥60seconds sustained decode, TTFT, retractions, all-node memory/swap/errors. An allocated7M-token pool is not this test.
6. Accuracy: run a frozen deployment-quality battery and matched native control before asserting the user's87%retention. Upstream reports absolute scores and quantized-sibling comparisons, not this native-relative guarantee. Latest8192 indexer changes and our reconstructed build both need fresh measurements.

Published claims remain reference evidence only: short-code C8~28.4TPS median,20/20 needle tests to997,952tokens, genuine image/video gates, GSM8K97.5%/IFEval80.0%/tool-eval85.5atloweffort. No public run proves six/eight independent500k vision streams at those speeds or87%native retention.

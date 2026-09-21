# Fair-prefill memory review before the 0.80 retry

Read-only source review; no SSH, API, GPU tests, deployment changes, or edits to
frozen serving files. The recommendation is to lower GPU memory utilization from
0.88 to **0.80**, preserving quantization, index top-k, vision, C8, 1M model limit,
DFlash7, batch 2304 and long-prefill threshold 256. This reserves more host memory
while the source-derived cache requirement still fits the projected smaller pool.
The projection must be replaced by the new launch's actual pool/block evidence.

## Observed evidence and unresolved allocation attribution

The saved actual fair-v2 startup (`evidence/rank0/startup-fair-v2.log`) records:

- Total device memory **121.69 GiB**, requested memory **107.09 GiB** at 0.88.
- Available KV **49.97 GiB**, global pool **2,563 blocks**, **365 blocks per 1M
  request**, reported equivalent pool **7,021,917 tokens**.
- Consumed weights/non-torch memory 55.39 GiB; profiled activation peak 1.73 GiB.
- Effective attention block 3,328; draft sliding-window block 256; locked shared
  workspace resize to 513 MiB.

Root reported that the real C8 × 500k wave reached head MemAvailable 1.83–1.88 GiB,
with workers at 2.79/3.79 GiB. The client was canceled and the server drained;
there was no observed OOM. These are observed pressure readings, **not a proven
allocation diagnosis or a completed capacity qualification**. Existing swap usage
alone does not establish current swapping. No source review here establishes
physical residency or rules out allocator retention, host request copies, driver
memory, other processes, or unreviewed runtime paths.

KV cache occupancy is the fraction of allocated pool block IDs in use. It is not
the fraction of physical RAM allocated and must not be extrapolated into future
physical allocation from the reported 18% occupancy.

## Cache arithmetic

The DFlash port's GLM layout shares Mamba storage with MLA slots and tail storage
with indexer slots. Its physical bytes per global block are:

```
11 × 1,703,936 MLA + 11 × 109,824 indexer + 5 × 196,608 draft
= 20,934,400 bytes
2,563 blocks × 20,934,400 bytes = 49.969989 GiB
```

This independently reproduces the actual v2 KV allocation. With an unchanged
non-KV profile and total memory, the projected effect is:

| Utilization | Additional host budget | Projected blocks | Reported pool equivalent |
| --- | ---: | ---: | ---: |
| 0.82 | 7.3014 GiB | about 2,188 | about 5.995M tokens |
| **0.80** | **9.7352 GiB** | **about 2,063** | **about 5.652M tokens** |

These subtract the rounded-up lost block count from the observed 2,563. They do
not predict boot-to-boot profiling variation or the binding rank with certainty.

A conservative **520,000 total sequence-token bound per request**, covering the
prepared 500–505k text, one allowed image up to 8k tokens, template overhead and
this test's output budget, gives:

```
ceil(520000 / 3328) + 1 tail + 4×9 Mamba + 27 draft = 221 blocks/request
8 × 221 + 1 null block = 1,769 blocks
```

The 0.80 projection leaves approximately 294 blocks beyond that bound. Inspect
actual per-group geometry and available blocks after launch; require comfortable
margin above 1,769. This estimate does not establish eight simultaneous 1M-token
requests, arbitrary larger image bundles, or actual long-context correctness.

The collector already accepts `--min-reported-pool-tokens 5400000`, corresponding
to approximately 1,971 blocks if the observed denominator remains 365. Its default
6M guard would reject the expected 0.80 pool despite this smaller test fitting.
Using the explicit override changes only the evidence guard, not serving capacity.

## Which reviewed workspaces can grow

- **Indexer K-gather:** sized at construction from the configured context/C8 and
  bounded by the applied patch; shared allocation is locked at 513 MiB. Runtime
  uses slices. It is not resized in proportion to a request's growing context.
- **Indexer prefill logits:** depend on query tokens × compressed context, but
  `split_indexer_prefill_chunks` bounds each chunk by the default 512 MiB
  `VLLM_SPARSE_INDEXER_MAX_LOGITS_MB`. At eight approximately 500k contexts with
  256 queries each and compression 4, a two-request chunk is approximately
  488 MiB; larger groups are split. This is a per-tensor limit, not a global
  allocator-peak guarantee. The previous Python-bound logits tensor may remain
  live while its replacement is allocated.
- **Indexer metadata:** `token_to_seq` is int32 over compressed context. Across
  eight 500k contexts this is about 4 MB per metadata set; it scales with context
  but is not itself a many-GiB matrix.
- **Actual CUSTOM MLA backend:** cuda-exl3 inherits vLLM's `SparseMLACommonImpl`
  and `FlashInferMLASparseMetadataBuilder`; it does not use the separate
  FlashMLA sparse backend's 5×context gather allocation. Its base chunked-prefill
  workspace is allocated at builder initialization and capped at 65,536 rows,
  about 64 MiB for the model's 512 BF16 latent dimensions. Actual startup reports
  that this model uses the sparse top-k MQA path rather than dense-MHA prefill.
- **FlashKDA:** patched scratch, final-state and output buffer shapes derive from
  max batch 2304, max sequences 8 and head dimensions at initialization. They
  do not scale with the already processed sequence length.

The reviewed paths therefore do not show an unbounded large workspace that must
continue growing linearly through the remaining 500k prefill. This is insufficient
to attribute the real memory pressure, and memory monitoring remains necessary.
No further workspace reduction or precision change is recommended for this retry.

## Exact source identity

- vLLM **487ecf187**, installed version `0.1.dev20051+g487ecf187`:
  `vllm/v1/attention/backends/mla/indexer.py` (splitter lines 81–127,
  metadata construction lines 1100–1148 and 1331–1355);
  `vllm/model_executor/layers/sparse_attn_indexer_kpool.py`
  (profile sentinel lines 279–318, prefill allocation lines 482–530);
  `vllm/model_executor/layers/attention/sparse_mla_attention.py`
  (builder allocations lines 136–165 and sizing lines 185–202);
  `vllm/envs.py` (512 MiB logits default).
- Recipe **7f1bd29cf473548212b8b731c52dcf2c7aa5a033**:
  `upstream/patches/dflash2-port/files/vllm/v1/core/kv_cache_utils.py`
  (`_pool_bytes_per_block`, GLM tensor allocation and
  `_harem_draft_bytes_per_block`); prepared
  `patch-indexer-workspace-tp3.py`, `patch-flashkda-tp3.py` and
  `patch-kvdiag-tp3.py`.
- cuda-exl3 **754421fc99919317b9a4cf2928797bae8f870040**:
  `cuda-exl3/src/cuda_exl3/attention.py` (CUSTOM backend inheritance and MQA path).
- Built image identity remains
  `sha256:af1cd7490e0bd7f47c3ede8752e87625f3e080a4f5224d9191ca455aa56cdfbb`.

Paths above are relative to this directory for local artifacts and to the pinned
vLLM source root where specified. Observations from the 0.80 launch are pending
and are intentionally not represented as measured results here.

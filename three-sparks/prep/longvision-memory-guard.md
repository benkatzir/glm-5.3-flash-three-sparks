# Private long-test memory guard

Run on the head as root after the specific CPU client container exists. This guard
does not launch the client, change a node, or stop any model server.

```bash
sudo python3 /path/to/longvision-memory-guard.py \
  --client-container glm53-longvision-c8-fair-v3 \
  --output /path/to/private/fair-v3-memory-guard
```

The output directory must be fresh. It is created mode 0700; JSONL and summary files
are private. Root should substitute the actual exact client name. The expected image
is pinned to `sha256:af1cd7490e0bd7f47c3ede8752e87625f3e080a4f5224d9191ca455aa56cdfbb`.

Preflight requires the exact requested `glm53-longvision-...` name, that image ID,
and a direct `python3 [-u] .../longvision-c8.py run` process. It rejects GPU/device
requests, privileged mode, non-runc runtime, device/host-root mounts, auto-restart,
and paused/restarting clients. It then captures the full immutable container ID.
Every control action uses that ID, never a name resolved again or a name pattern.

Every five seconds, the guard reads only `/proc/meminfo`'s `MemAvailable`: locally
on the head and through parallel passwordless fabric SSH as `ben` on both workers.
It uses these existing host-key aliases, without modifying known hosts:

| Worker | Fabric address | HostKeyAlias |
|---|---|---|
| worker1 | WORKER1_FABRIC_IP | WORKER1_MGMT_IP |
| worker2 | WORKER2_FABRIC_IP | WORKER2_MGMT_IP |

SSH uses BatchMode, ConnectTimeout=3, ServerAliveInterval=3 and
ServerAliveCountMax=1. Each read has an eight-second subprocess timeout. Normal
samples begin five seconds apart; an individual failed/slow cycle may take longer.
All three memory readings execute in parallel, so two stalled workers do not create
two serial timeout intervals.

On any node, two consecutive valid readings **below 3 GiB** trigger cancellation.
Three consecutive read failures also trigger cancellation. A successful reading
resets that node's failure counter; a read failure breaks its low-memory streak.
Three consecutive Docker inspection failures also fail closed against the same
already validated client ID.

The guard sends `docker kill --signal INT CONTAINER_ID`, allows a full 20-second
grace, and, if the client is still running or its state cannot be read, uses
`docker stop --timeout 10 CONTAINER_ID`. Each action/outcome is logged. Failure to
confirm the client exited is reported explicitly. No model container is a target.

The guard finishes when the client exits. SIGINT, SIGTERM or SIGHUP to the guard
also cancels its client, so stopping the guard does not silently leave an unguarded
wave. The default maximum is 95 minutes, including a reserved 90 seconds for an
in-flight poll and the interrupt/stop sequence. It therefore begins deadline
cancellation after 93.5 minutes if the client remains alive. `--max-seconds` can
shorten that bound (120–5700); the client itself retains its own 90-minute deadline.

`guard.jsonl` retains every sample, streak and action. `summary.json` records memory
floors, trigger reasons and whether stopping was confirmed. Exit 0 means the client
was observed exited without a guard-triggered cancellation; exit 2 means the guard
triggered or encountered a monitoring/control error. It does not assert the model
requests succeeded; inspect the long client's separate result files.

Offline tests:

```bash
python3 test-longvision-memory-guard.py
```

Four mocked test groups passed: preflight rejects serving/GPU identities, threshold
and failure streak behavior, fixed read-only SSH commands, and immutable-ID-only
interrupt/escalation with a full grace period. No Docker, SSH, GPU, live API or
process-signal actions were performed during implementation.

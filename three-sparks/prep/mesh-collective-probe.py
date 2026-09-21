#!/usr/bin/env python3
"""Bounded, model-free CUDA/NCCL data-integrity probe for exactly three ranks.

Run one process per Spark with the same serving image, mesh plugin and transport
environment. Every received tensor element is checked. Nonzero exit on any
failure. A watchdog terminates a hung rank at the whole-process budget; peer
collectives also have a distributed timeout. --plan imports no torch or CUDA.
"""
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

EXPECTED_ENV = {
    "NCCL_NET": "Mesh", "NCCL_NET_PLUGIN": "mesh", "NCCL_IB_DISABLE": "1",
    "NCCL_ALGO": "Ring", "NCCL_CUMEM_ENABLE": "0", "NCCL_NVLS_ENABLE": "0",
    "NCCL_CROSS_NIC": "0", "NCCL_IB_MERGE_NICS": "0",
    "NCCL_IGNORE_CPU_AFFINITY": "1", "NCCL_MAX_NCHANNELS": "8",
    "NCCL_MESH_LINKS_PER_PEER": "0", "NCCL_MESH_MIN_RNR_TIMER": "1",
    "NCCL_MESH_PTR_CUDA": "1", "NCCL_MESH_FLUSH": "1",
    "GLOO_SOCKET_IFNAME": "MGMT_IFACE", "TP_SOCKET_IFNAME": "MGMT_IFACE",
    "MN_IF_NAME": "MGMT_IFACE", "NCCL_SOCKET_IFNAME": "=MGMT_IFACE",
}


def counters():
    out = {}
    for path in sorted(Path("/sys/class/infiniband").glob("*/ports/*/counters/*")):
        if path.name not in ("port_xmit_data", "port_rcv_data", "port_xmit_packets", "port_rcv_packets", "port_rcv_errors", "port_xmit_discards"):
            continue
        try:
            out["/".join(path.parts[-5:])] = int(path.read_text().strip())
        except (OSError, ValueError):
            pass
    return out


def write_json(fd, value):
    data = (json.dumps(value, sort_keys=True) + "\n").encode()
    while data:
        data = data[os.write(fd, data):]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rank", type=int, choices=range(3), default=int(os.environ.get("RANK", "-1")))
    parser.add_argument("--master-addr", default=os.environ.get("MASTER_ADDR"))
    parser.add_argument("--master-port", type=int, default=int(os.environ.get("MASTER_PORT", "29577")))
    parser.add_argument("--budget-seconds", type=int, default=60)
    parser.add_argument("--distributed-timeout-seconds", type=int, default=20)
    parser.add_argument("--sizes", default="17,4096,4194304", help="Float32 elements, comma separated; largest default payload is 16 MiB.")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--plugin", type=Path, default=Path("/opt/nccl-mesh/libnccl-net-mesh.so"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.rank not in range(3) or not args.master_addr:
        parser.error("rank 0..2 and master address are required")
    if not 1024 <= args.master_port <= 65535:
        parser.error("master port must be 1024..65535")
    if not 5 <= args.budget_seconds <= 60 or not 2 <= args.distributed_timeout_seconds < args.budget_seconds:
        parser.error("budget must be 5..60 s; distributed timeout must be >=2 s and shorter than budget")
    try:
        sizes = [int(x) for x in args.sizes.split(",")]
    except ValueError:
        parser.error("sizes must be comma-separated integers")
    if not sizes or len(sizes) > 8 or any(n < 1 or n > 16777216 for n in sizes) or not 1 <= args.repeats <= 3:
        parser.error("use 1..8 sizes of 1..16777216 elements and 1..3 repeats")
    plan = {"rank": args.rank, "world_size": 3, "dtype": "float32", "sizes_elements": sizes,
            "payload_bytes": [n * 4 for n in sizes], "repeats": args.repeats,
            "operations": ["all_reduce_sum", "all_gather"], "budget_seconds": args.budget_seconds,
            "distributed_timeout_seconds": args.distributed_timeout_seconds, "required_environment": EXPECTED_ENV}
    if args.plan:
        print(json.dumps(plan, indent=2))
        return
    started = time.monotonic()
    result = {"schema": "glm53.mesh-collective-probe.v1", **plan, "state": "running", "stages": [],
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "One bounded model-free collective-integrity run; not GLM model validation or exhaustive transport qualification."}
    output_fd = None
    if args.output:
        output_fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    phase = ["preflight"]
    finish_lock = threading.Lock()
    finished = [False]

    def timed_out():
        timeout_result = {"schema": result["schema"], "rank": args.rank, "world_size": 3,
                          "state": "timeout", "phase": phase[0], "elapsed_seconds": time.monotonic() - started,
                          "budget_seconds": args.budget_seconds, "completed_stages": list(result["stages"])}
        with finish_lock:
            if finished[0]:
                return
            try:
                if output_fd is not None:
                    write_json(output_fd, timeout_result)
                write_json(1, timeout_result)
            finally:
                os._exit(124)

    watchdog = threading.Timer(args.budget_seconds, timed_out)
    watchdog.daemon = True
    watchdog.start()
    exit_code = 1
    try:
        mismatches = {key: {"expected": value, "actual": os.environ.get(key)}
                      for key, value in EXPECTED_ENV.items() if os.environ.get(key) != value}
        if mismatches:
            result["environment_mismatches"] = mismatches
            raise RuntimeError("Serving mesh transport environment mismatch")
        result["plugin_sha256"] = hashlib.sha256(args.plugin.read_bytes()).hexdigest()
        phase[0] = "torch_import_and_cuda_init"
        import torch
        import torch.distributed as dist
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise RuntimeError("Exactly one visible CUDA device per rank is required")
        torch.cuda.set_device(0)
        result["torch_version"] = torch.__version__
        result["cuda_version"] = torch.version.cuda
        result["nccl_version"] = torch.cuda.nccl.version()
        result["rdma_counters_before"] = counters()
        phase[0] = "init_process_group"
        begin = time.monotonic()
        dist.init_process_group("nccl", rank=args.rank, world_size=3,
            init_method=f"tcp://{args.master_addr}:{args.master_port}",
            timeout=timedelta(seconds=args.distributed_timeout_seconds), device_id=torch.device("cuda:0"))
        result["init_seconds"] = time.monotonic() - begin
        sequence = 0
        for repeat in range(args.repeats):
            for n in sizes:
                # All input and expected values are exactly representable integers
                # in float32. Vary by element, rank, size/repeat, and operation.
                sequence += 1
                base = (torch.arange(n, device="cuda", dtype=torch.int64) % 251).to(torch.float32)
                offset = sequence * 8
                for operation in ("all_reduce_sum", "all_gather"):
                    phase[0] = f"{operation}:repeat={repeat}:elements={n}"
                    data = base + (args.rank + 1) * 512 + offset
                    if operation == "all_gather":
                        received = [torch.full_like(data, float("nan")) for _ in range(3)]
                    torch.cuda.synchronize()
                    begin = time.monotonic()
                    if operation == "all_reduce_sum":
                        dist.all_reduce(data, op=dist.ReduceOp.SUM)
                    else:
                        dist.all_gather(received, data)
                    torch.cuda.synchronize()
                    collective_seconds = time.monotonic() - begin
                    check_begin = time.monotonic()
                    if operation == "all_reduce_sum":
                        expected = base * 3 + 512 * 6 + offset * 3
                        if not torch.equal(data, expected):
                            result["mismatched_elements"] = int(torch.count_nonzero(data != expected).item())
                            raise AssertionError("all_reduce full-tensor mismatch")
                        checked = n
                    else:
                        for peer_rank, tensor in enumerate(received):
                            expected = base + (peer_rank + 1) * 512 + offset
                            if not torch.equal(tensor, expected):
                                result["mismatched_peer_rank"] = peer_rank
                                result["mismatched_elements"] = int(torch.count_nonzero(tensor != expected).item())
                                raise AssertionError("all_gather full-tensor mismatch")
                        checked = n * 3
                        del received
                    result["stages"].append({"operation": operation, "repeat": repeat,
                        "elements_per_rank": n, "payload_bytes_per_rank": n * 4,
                        "collective_seconds": collective_seconds,
                        "full_tensor_check_seconds": time.monotonic() - check_begin,
                        "checked_elements": checked, "state": "passed"})
                    write_json(1, {"event": "stage_passed", "rank": args.rank, **result["stages"][-1]})
                    del data, expected
                del base
        phase[0] = "final_barrier_and_destroy"
        dist.barrier(device_ids=[0])
        torch.cuda.synchronize()
        result["rdma_counters_after"] = counters()
        result["rdma_counter_deltas"] = {key: value - result["rdma_counters_before"][key]
            for key, value in result["rdma_counters_after"].items() if key in result["rdma_counters_before"]}
        result["counter_scope"] = "Host port counters; concurrent fabric traffic can contribute. Inspect transport logs and peer results too."
        dist.destroy_process_group()
        result["state"] = "passed"
        exit_code = 0
    except Exception as exc:
        result.update(state="failed", phase=phase[0], error_type=type(exc).__name__)
        # Print bounded failure context; no environment dump or API credentials.
        result["error"] = str(exc)[:2000]
    finally:
        with finish_lock:
            finished[0] = True
            watchdog.cancel()
            result["elapsed_seconds"] = time.monotonic() - started
            result["completed_stage_count"] = len(result["stages"])
            if output_fd is not None:
                write_json(output_fd, result)
                os.close(output_fd)
            write_json(1, result)
    # Failed NCCL teardown can itself hang in interpreter finalizers. Exiting
    # immediately after the recorded result leaves Docker to reap only this probe.
    os._exit(exit_code)


if __name__ == "__main__":
    main()

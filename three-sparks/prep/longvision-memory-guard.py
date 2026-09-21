#!/usr/bin/env python3
"""Guard only an identified CPU longvision client; never stop model containers."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

IMAGE = "sha256:af1cd7490e0bd7f47c3ede8752e87625f3e080a4f5224d9191ca455aa56cdfbb"
MIN_KIB = 3 * 1024 * 1024
POLL_SECONDS = 5
MAX_SECONDS = 95 * 60
AWK_PROGRAM = '/^MemAvailable:/ {print $2; found=1} END {if (!found) exit 2}'
REMOTE_COMMAND = "awk '" + AWK_PROGRAM + "' /proc/meminfo"
WORKERS = {"worker1": ("WORKER1_MGMT_IP", "WORKER1_FABRIC_IP"), "worker2": ("WORKER2_MGMT_IP", "WORKER2_FABRIC_IP")}


def command(argv, timeout=8):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=timeout, check=False)
    if result.returncode:
        # Do not copy arbitrary Docker environment/SSH output into guard logs.
        raise RuntimeError("command_exit_" + str(result.returncode))
    return result.stdout


def inspect(identifier):
    result = json.loads(command(["docker", "container", "inspect", identifier]))
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError("Expected one exact container")
    return result[0]


def validate_container(data, name):
    if not re.fullmatch(r"glm53-longvision-[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", name):
        raise ValueError("Only an explicit glm53-longvision-... client name is allowed")
    if data.get("Name") != "/" + name or data.get("Image") != IMAGE:
        raise ValueError("Client name or image identity mismatch")
    identifier = data.get("Id", "")
    if not re.fullmatch(r"[0-9a-f]{64}", identifier):
        raise ValueError("Full immutable container ID required")
    if Path(data.get("Path", "")).name != "python3":
        raise ValueError("Client must directly execute python3")
    args = data.get("Args") or []
    if args[:1] == ["-u"]:
        args = args[1:]
    if len(args) < 2 or Path(args[0]).name != "longvision-c8.py" or args[1] != "run":
        raise ValueError("Client must directly run longvision-c8.py run")
    host = data.get("HostConfig") or {}
    if (host.get("Privileged") or host.get("DeviceRequests") or host.get("Devices") or
            host.get("DeviceCgroupRules") or host.get("Runtime", "runc") not in ("", "runc")):
        raise ValueError("Only an unprivileged CPU client without device requests is allowed")
    for mount in data.get("Mounts") or []:
        source, destination = mount.get("Source", ""), mount.get("Destination", "")
        if (source == "/" or source == "/dev" or source.startswith("/dev/") or
                destination == "/dev" or destination.startswith("/dev/")):
            raise ValueError("Client device or host-root mounts are not allowed")
    state = data.get("State") or {}
    if state.get("Paused") or state.get("Restarting"):
        raise ValueError("Client is paused or restarting")
    if (host.get("RestartPolicy") or {}).get("Name", "no") not in ("", "no"):
        raise ValueError("Client must not have an automatic restart policy")
    return identifier


def mem_command(node):
    if node == "head":
        return ["awk", AWK_PROGRAM, "/proc/meminfo"]
    alias, address = WORKERS[node]
    return ["runuser", "-u", "ben", "--", "ssh", "-n", "-T",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=3",
            "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=1",
            "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no",
            "-o", "LogLevel=ERROR", "-o", "HostKeyAlias=" + alias,
            "ben@" + address, REMOTE_COMMAND]


def read_memory(node):
    begin = time.monotonic_ns()
    try:
        output = command(mem_command(node)).strip()
        if not re.fullmatch(r"[0-9]+", output) or int(output) <= 0:
            raise ValueError("Malformed MemAvailable")
        return {"node": node, "start_ns": begin, "end_ns": time.monotonic_ns(),
                "mem_available_kib": int(output), "mem_available_gib": int(output) / 1048576}
    except Exception as exc:
        return {"node": node, "start_ns": begin, "end_ns": time.monotonic_ns(),
                "error_type": type(exc).__name__}


class Consecutive:
    def __init__(self):
        self.low = {node: 0 for node in ("head", *WORKERS)}
        self.failed = dict(self.low)

    def update(self, readings):
        reasons = []
        for row in readings:
            node = row["node"]
            if "mem_available_kib" in row:
                self.failed[node] = 0
                self.low[node] = self.low[node] + 1 if row["mem_available_kib"] < MIN_KIB else 0
            else:
                self.failed[node] += 1
                self.low[node] = 0
            row["consecutive_low"] = self.low[node]
            row["consecutive_read_failures"] = self.failed[node]
            if self.low[node] >= 2:
                reasons.append({"node": node, "reason": "two_consecutive_below_3GiB"})
            if self.failed[node] >= 3:
                reasons.append({"node": node, "reason": "three_consecutive_read_failures"})
        return reasons


def stop_client(identifier, emit):
    """Only accepts the already validated immutable ID, never a mutable name."""
    if not re.fullmatch(r"[0-9a-f]{64}", identifier):
        raise ValueError("Refusing a non-immutable stop target")
    try:
        data = inspect(identifier)
        if not data.get("State", {}).get("Running"):
            emit({"event": "client_already_exited", "container_id": identifier})
            return "already_exited"
    except Exception as exc:
        emit({"event": "pre_interrupt_inspect_failed", "error_type": type(exc).__name__})
        # The ID was validated before monitoring and cannot be reused by another container.
    try:
        command(["docker", "kill", "--signal", "INT", identifier])
        emit({"event": "client_interrupt_sent", "container_id": identifier})
    except Exception as exc:
        emit({"event": "client_interrupt_failed", "error_type": type(exc).__name__})
    grace_end = time.monotonic() + 20
    while time.monotonic() < grace_end:
        try:
            if not inspect(identifier).get("State", {}).get("Running"):
                emit({"event": "client_exited_after_interrupt"})
                return "exited_after_interrupt"
        except Exception as exc:
            emit({"event": "grace_inspect_failed", "error_type": type(exc).__name__})
        time.sleep(min(1, max(0, grace_end - time.monotonic())))
    try:
        # Stop timeout bounds Docker's TERM-to-KILL grace; command gets a small API margin.
        command(["docker", "stop", "--timeout", "10", identifier], timeout=15)
        emit({"event": "client_stop_completed", "container_id": identifier})
    except Exception as exc:
        emit({"event": "client_stop_failed", "error_type": type(exc).__name__})
        return "stop_failed"
    try:
        if inspect(identifier).get("State", {}).get("Running"):
            emit({"event": "client_still_running"})
            return "still_running"
    except Exception as exc:
        emit({"event": "post_stop_inspect_failed", "error_type": type(exc).__name__})
        return "stop_returned_but_exit_unconfirmed"
    return "stopped_after_grace"


def run(args):
    if os.geteuid() != 0:
        raise ValueError("Run the guard as root on the head")
    if not 120 <= args.max_seconds <= MAX_SECONDS:
        raise ValueError("max-seconds must be 120..5700")
    # Validate before creating output or authorizing any control action.
    initial = inspect(args.client_container)
    identifier = validate_container(initial, args.client_container)
    args.output.mkdir(parents=True, exist_ok=False); args.output.chmod(0o700)
    logfile = (args.output / "guard.jsonl").open("x")
    begin = time.monotonic()
    interrupted = threading.Event()
    def handle_signal(signum, _frame):
        interrupted.set()
    signal.signal(signal.SIGINT, handle_signal); signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGHUP, handle_signal)
    def emit(row):
        record = {"wall_ns": time.time_ns(), "monotonic_ns": time.monotonic_ns(), **row}
        logfile.write(json.dumps(record) + "\n"); logfile.flush()
    emit({"event": "preflight_pass", "client_name": args.client_container, "container_id": identifier,
          "image_id": IMAGE, "entrypoint": "python3 longvision-c8.py run", "cpu_only": True,
          "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "poll_seconds": POLL_SECONDS, "minimum_gib": 3, "max_seconds": args.max_seconds})
    streak = Consecutive(); inspections_failed = 0; polls = 0
    reasons = []; state = "client_exited"; outcome = None
    floors = {node: None for node in ("head", *WORKERS)}
    # Reserve 90s for an in-flight 16s poll and at most 66s of stop/inspection APIs.
    monitor_deadline = begin + args.max_seconds - 90
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            while True:
                cycle = time.monotonic()
                if interrupted.is_set():
                    reasons = [{"reason": "guard_interrupted"}]; state = "guard_interrupted"; break
                if cycle >= monitor_deadline:
                    reasons = [{"reason": "guard_monitor_deadline"}]; state = "guard_deadline"; break
                try:
                    current = inspect(identifier)
                    if current.get("Id") != identifier:
                        raise ValueError("Immutable identity mismatch")
                    inspections_failed = 0
                    if not current.get("State", {}).get("Running"):
                        state = "client_exited"; break
                except Exception as exc:
                    inspections_failed += 1
                    emit({"event": "client_inspect_failed", "consecutive_failures": inspections_failed,
                          "error_type": type(exc).__name__})
                    if inspections_failed >= 3:
                        reasons = [{"reason": "three_consecutive_client_inspect_failures"}]
                        state = "monitor_failure"; break
                readings = list(pool.map(read_memory, ("head", *WORKERS)))
                polls += 1
                reasons = streak.update(readings)
                for row in readings:
                    node, value = row["node"], row.get("mem_available_kib")
                    if value is not None and (floors[node] is None or value < floors[node]): floors[node] = value
                emit({"event": "memory_sample", "poll": polls, "readings": readings})
                if reasons:
                    state = "memory_margin_or_read_failure"; break
                interrupted.wait(max(0, POLL_SECONDS - (time.monotonic() - cycle)))
        if reasons:
            emit({"event": "client_stop_trigger", "reasons": reasons})
            outcome = stop_client(identifier, emit)
    except Exception as exc:
        state = "guard_internal_error"; reasons = [{"reason": state, "error_type": type(exc).__name__}]
        emit({"event": state, "error_type": type(exc).__name__})
        outcome = stop_client(identifier, emit)
    finally:
        summary = {"schema": "glm53.longvision-memory-guard.v1", "state": state,
                   "client_name": args.client_container, "container_id": identifier, "image_id": IMAGE,
                   "polls": polls, "minimum_mem_available_kib": floors,
                   "trigger_reasons": reasons, "stop_outcome": outcome,
                   "elapsed_seconds": time.monotonic() - begin,
                   "scope": "Only the validated CPU client container can be signaled or stopped; model containers are never targets."}
        with (args.output / "summary.json").open("x") as out: json.dump(summary, out, indent=2); out.write("\n")
        logfile.close()
    print(json.dumps(summary, indent=2))
    return 0 if state == "client_exited" else 2


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-container", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-seconds", type=int, default=MAX_SECONDS)
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__": main()

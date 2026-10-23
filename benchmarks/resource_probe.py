#!/usr/bin/env python3
"""CI-only resource observation for a benchmark process and PostgreSQL host.

Records snapshots while the child process runs. These are runner-wide
measurements, not exact per-backend private memory nor PostgreSQL temp
allocations; record the limitations rather than present them as judge metrics.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time


def memory_available_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def postgres_rss_bytes() -> int | None:
    # Process RSS sums double-count PostgreSQL shared memory. Useful for
    # relative per-case trends only, not authoritative peak unique RAM.
    try:
        p = subprocess.run(
            ["ps", "-eo", "rss=,comm="],
            capture_output=True, text=True, check=True, timeout=5
        )
        total = 0
        for row in p.stdout.splitlines():
            pieces = row.split(maxsplit=1)
            if len(pieces) == 2 and pieces[1].startswith("postgres"):
                total += int(pieces[0]) * 1024
        return total
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--interval", type=float, default=2)
    p.add_argument("command", nargs=argparse.REMAINDER)
    args = p.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        p.error("Supply a command after --")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    stopping = threading.Event()
    start = time.monotonic()

    def monitor() -> None:
        while not stopping.is_set():
            disk = shutil.disk_usage("/")
            samples.append({
                "elapsed_s": round(time.monotonic() - start, 1),
                "root_used_bytes": disk.used,
                "root_free_bytes": disk.free,
                "mem_available_bytes": memory_available_bytes(),
                "postgres_rss_sum_bytes": postgres_rss_bytes(),
            })
            stopping.wait(args.interval)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    child = None
    code = 1
    try:
        child = subprocess.Popen(command)
        code = child.wait()
    finally:
        stopping.set()
        thread.join(timeout=10)
        if not samples:
            samples.append({"elapsed_s": 0})
        metrics = {
            "argv": command,
            "exit_code": code,
            "duration_s": round(time.monotonic() - start, 2),
            "sampling_period_s": args.interval,
            "observations": len(samples),
            "peak_root_used_gb": round(max(s["root_used_bytes"] for s in samples
                                             if "root_used_bytes" in s) / (1024**3), 3),
            "minimum_root_free_gb": round(min(s["root_free_bytes"] for s in samples
                                             if "root_free_bytes" in s) / (1024**3), 3),
            "minimum_mem_available_gb": round(min(s["mem_available_bytes"] for s in samples
                              if s.get("mem_available_bytes") is not None) / (1024**3), 3)
                   if any(s.get("mem_available_bytes") is not None for s in samples) else None,
            "peak_postgres_rss_sum_gb": round(max(s["postgres_rss_sum_bytes"] for s in samples
                              if s.get("postgres_rss_sum_bytes") is not None) / (1024**3), 3)
                   if any(s.get("postgres_rss_sum_bytes") is not None for s in samples) else None,
            "warning": "Runner-wide disk and free memory; PostgreSQL RSS sums may double-count shared pages. Neither is an official adjudicated resource measurement.",
            "start_snapshot": samples[0],
            "end_snapshot": samples[-1],
        }
        args.out.write_text(json.dumps(metrics, indent=2) + "\n")
        print("RESOURCE_PROBE " + json.dumps({
            k: v for k, v in metrics.items()
            if k not in ("argv", "start_snapshot", "end_snapshot")
        }), flush=True)
    sys.exit(code)


if __name__ == "__main__":
    main()

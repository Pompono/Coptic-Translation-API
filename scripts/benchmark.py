#!/usr/bin/env python3
"""Measure live API latency with uncached requests; does not simulate model work."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SAMPLES = [
    ("ⲁⲙⲏⲛ", "coptic_to_english", "sahidic"),
    ("ⲡⲉⲛⲛⲟⲩϯ", "coptic_to_english", "bohairic"),
    ("ⲓⲏⲥⲟⲩⲥ ⲡⲭⲣⲓⲥⲧⲟⲥ", "coptic_to_english", "bohairic"),
    ("amen", "english_to_coptic", "bohairic"),
    ("God", "english_to_coptic", "bohairic"),
    ("Jesus Christ", "english_to_coptic", "sahidic"),
]


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * p) - 1)]


def request(url: str, payload: dict, api_key: str | None) -> tuple[int, bool, float]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            result = json.loads(response.read())
            return response.status, bool(result.get("cached")), time.perf_counter() - start
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"API request returned HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()

    ready_start = time.perf_counter()
    with urllib.request.urlopen(f"{args.url.rstrip('/')}/health/ready", timeout=300) as response:
        ready = json.loads(response.read())
    ready_check_seconds = time.perf_counter() - ready_start

    latencies: list[float] = []
    cache_miss = cache_hit = 0
    benchmark_started = time.perf_counter()
    for repeat in range(args.repeats):
        for text, direction, dialect in SAMPLES:
            status, cached, elapsed = request(args.url.rstrip("/") + "/v1/translate", {
                "text": text + ("." * repeat), "direction": direction, "dialect": dialect
            }, args.api_key)
            if status != 200:
                raise RuntimeError(f"Unexpected status {status}")
            latencies.append(elapsed)
            if cached:
                cache_hit += 1
            else:
                cache_miss += 1

    wall_time = time.perf_counter() - benchmark_started
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "api_url": args.url,
        "device": ready.get("device"),
        "model_load_seconds": ready.get("model_load_seconds"),
        "ready_probe_seconds": round(ready_check_seconds, 4),
        "requests": len(latencies),
        "wall_time_seconds": round(wall_time, 4),
        "uncached_requests": cache_miss,
        "cached_requests": cache_hit,
        "latency_seconds": {
            "p50": round(statistics.median(latencies), 4),
            "p95": round(percentile(latencies, .95), 4),
            "min": round(min(latencies), 4),
            "max": round(max(latencies), 4),
            "mean": round(statistics.mean(latencies), 4),
        },
        "sequential_throughput_requests_per_second": round(len(latencies) / wall_time, 3) if wall_time else None,
        "note": "Model load time is recorded by the API process during its lifespan startup.",
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

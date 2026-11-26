#!/usr/bin/env python3
"""Loopback benchmark: FlpIt's urllib3-backed HttpClient vs HTTPX.

Run from the repository root:

    uv run python benchmarks/scripts/http_client_bench.py

The script measures connection-reused HTTP/1.1 requests against a local server.
It reports steady-state throughput and sequential latency; concurrent throughput
is reported separately because FlpIt Tasks and HTTPX coroutines have different
scheduling models.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import math
import os
import platform
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import urllib3

from flpit.http import HttpClient, HttpClientHandler


BODY = b'{"ok":true,"message":"hello","count":42,"payload":"' + b"x" * 80 + b'"}'


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *_: object) -> None:
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _sequential_flpit(client: HttpClient, path: str, count: int) -> tuple[list[float], float]:
    latencies: list[float] = []
    started = time.perf_counter()
    for _ in range(count):
        call_started = time.perf_counter()
        response = client.get_async(path).result(timeout=20)
        try:
            assert response.status_code == 200
            assert response.content.read_as_bytes_async().result(timeout=20) == BODY
        finally:
            response.close()
        latencies.append(time.perf_counter() - call_started)
    return latencies, time.perf_counter() - started


def _sequential_httpx(client: httpx.Client, url: str, count: int) -> tuple[list[float], float]:
    latencies: list[float] = []
    started = time.perf_counter()
    for _ in range(count):
        call_started = time.perf_counter()
        response = client.get(url)
        assert response.status_code == 200 and response.content == BODY
        response.close()
        latencies.append(time.perf_counter() - call_started)
    return latencies, time.perf_counter() - started


def _concurrent_flpit(client: HttpClient, path: str, count: int) -> float:
    started = time.perf_counter()
    tasks = [client.get_async(path) for _ in range(count)]
    for task in tasks:
        response = task.result(timeout=30)
        try:
            assert response.status_code == 200
            assert response.content.read_as_bytes_async().result(timeout=20) == BODY
        finally:
            response.close()
    return time.perf_counter() - started


def _concurrent_httpx_sync(client: httpx.Client, url: str, count: int,
                           workers: int) -> float:
    def one(_: int) -> None:
        response = client.get(url)
        try:
            assert response.status_code == 200 and response.content == BODY
        finally:
            response.close()

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(one, range(count)))
    return time.perf_counter() - started


async def _concurrent_httpx_async(client: httpx.AsyncClient, url: str,
                                  count: int) -> float:
    async def one() -> None:
        response = await client.get(url)
        try:
            assert response.status_code == 200 and response.content == BODY
        finally:
            await response.aclose()

    started = time.perf_counter()
    await asyncio.gather(*(one() for _ in range(count)))
    return time.perf_counter() - started


def _summary(latencies: list[float], count: int, wall: float) -> dict[str, float]:
    return {
        "requests": count,
        "wall_seconds": wall,
        "requests_per_second": count / wall,
        "latency_median_ms": statistics.median(latencies) * 1000,
        "latency_p95_ms": _percentile(latencies, 0.95) * 1000,
        "latency_p99_ms": _percentile(latencies, 0.99) * 1000,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrent-requests", type=int, default=128)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--out", default="benchmark-results/http-client.json")
    args = parser.parse_args()

    if min(args.requests, args.concurrent_requests, args.workers, args.repeats) <= 0:
        parser.error("requests, concurrent-requests, workers, and repeats must be positive")

    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/payload"
    path = "/payload"
    limits = httpx.Limits(
        max_connections=args.workers,
        max_keepalive_connections=args.workers,
    )
    results: dict[str, object] = {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "urllib3": urllib3.__version__,
            "httpx": httpx.__version__,
            "httpx_backend": "httpcore",
            "server": "ThreadingHTTPServer, loopback, HTTP/1.1 keep-alive",
            "payload_bytes": len(BODY),
            "workers": args.workers,
            "requests_per_sequential_trial": args.requests,
            "requests_per_concurrent_trial": args.concurrent_requests,
            "repeats": args.repeats,
            "warmup": args.warmup,
            "flpit_runtime": "repository Task runtime",
        },
        "sequential": {},
        "concurrent": {},
    }

    try:
        handler = HttpClientHandler(max_connections_per_host=args.workers)
        flpit_client = HttpClient(handler, base_address=url)
        httpx_client = httpx.Client(limits=limits, timeout=20)
        try:
            for _ in range(args.warmup):
                response = flpit_client.get_async(path).result(timeout=20)
                response.close()
                response = httpx_client.get(url)
                response.close()

            for name, runner in (
                ("flpit_http_urllib3", lambda: _sequential_flpit(flpit_client, path, args.requests)),
                ("httpx_sync", lambda: _sequential_httpx(httpx_client, url, args.requests)),
            ):
                trials: list[tuple[list[float], float]] = [runner() for _ in range(args.repeats)]
                walls = [wall for _, wall in trials]
                latencies = [latency for sample, _ in trials for latency in sample]
                results["sequential"][name] = _summary(
                    latencies, args.requests * args.repeats, statistics.median(walls)
                )

            concurrent_runners = {
                "flpit_http_urllib3": lambda: _concurrent_flpit(
                    flpit_client, path, args.concurrent_requests
                ),
                "httpx_sync": lambda: _concurrent_httpx_sync(
                    httpx_client, url, args.concurrent_requests, args.workers
                ),
            }
            for name, runner in concurrent_runners.items():
                walls = [runner() for _ in range(args.repeats)]
                median_wall = statistics.median(walls)
                results["concurrent"][name] = {
                    "requests_per_trial": args.concurrent_requests,
                    "median_wall_seconds": median_wall,
                    "requests_per_second": args.concurrent_requests / median_wall,
                }
        finally:
            flpit_client.close()
            httpx_client.close()

        async def run_async_trials() -> list[float]:
            async with httpx.AsyncClient(limits=limits, timeout=20) as client:
                for _ in range(args.warmup):
                    response = await client.get(url)
                    await response.aclose()
                return [
                    await _concurrent_httpx_async(client, url, args.concurrent_requests)
                    for _ in range(args.repeats)
                ]

        async_walls = asyncio.run(run_async_trials())
        async_median = statistics.median(async_walls)
        results["concurrent"]["httpx_async"] = {
            "requests_per_trial": args.concurrent_requests,
            "median_wall_seconds": async_median,
            "requests_per_second": args.concurrent_requests / async_median,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()

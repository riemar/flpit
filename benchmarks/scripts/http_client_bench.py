#!/usr/bin/env python3
"""Loopback benchmarks for FlpIt's urllib3 HttpClient vs HTTPX.

Measures paired synchronous and asynchronous API paths, sequentially and under
concurrency, against the same local HTTP/1.1 keep-alive server. FlpIt's async
API returns FlpIt Tasks; those Tasks execute the blocking urllib3 transport on
FlpIt's worker pool. HTTPX's async API uses httpcore's native asyncio transport.
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
from typing import Any, Callable

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


def _check_flpit(response: Any) -> None:
    assert response.status_code == 200
    assert response.content.read_as_bytes() == BODY


async def _check_flpit_async(response: Any) -> None:
    assert response.status_code == 200
    assert await response.content.read_as_bytes_async() == BODY


def _sequential_flpit_sync(client: HttpClient, path: str, count: int) -> tuple[list[float], float]:
    latencies: list[float] = []
    started = time.perf_counter()
    for _ in range(count):
        call_started = time.perf_counter()
        response = client.get(path)
        try:
            _check_flpit(response)
        finally:
            response.close()
        latencies.append(time.perf_counter() - call_started)
    return latencies, time.perf_counter() - started


async def _sequential_flpit_async(client: HttpClient, path: str,
                                  count: int) -> tuple[list[float], float]:
    latencies: list[float] = []
    started = time.perf_counter()
    for _ in range(count):
        call_started = time.perf_counter()
        response = await client.get_async(path)
        try:
            await _check_flpit_async(response)
        finally:
            response.close()
        latencies.append(time.perf_counter() - call_started)
    return latencies, time.perf_counter() - started


def _sequential_httpx_sync(client: httpx.Client, url: str,
                           count: int) -> tuple[list[float], float]:
    latencies: list[float] = []
    started = time.perf_counter()
    for _ in range(count):
        call_started = time.perf_counter()
        response = client.get(url)
        try:
            assert response.status_code == 200 and response.content == BODY
        finally:
            response.close()
        latencies.append(time.perf_counter() - call_started)
    return latencies, time.perf_counter() - started


async def _sequential_httpx_async(client: httpx.AsyncClient, url: str,
                                  count: int) -> tuple[list[float], float]:
    latencies: list[float] = []
    started = time.perf_counter()
    for _ in range(count):
        call_started = time.perf_counter()
        response = await client.get(url)
        try:
            assert response.status_code == 200 and response.content == BODY
        finally:
            await response.aclose()
        latencies.append(time.perf_counter() - call_started)
    return latencies, time.perf_counter() - started


def _concurrent_flpit_sync(client: HttpClient, path: str,
                           count: int, workers: int) -> float:
    def one(_: int) -> None:
        response = client.get(path)
        try:
            _check_flpit(response)
        finally:
            response.close()

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(one, range(count)))
    return time.perf_counter() - started


async def _concurrent_flpit_async(client: HttpClient, path: str, count: int) -> float:
    async def one() -> None:
        response = await client.get_async(path)
        try:
            await _check_flpit_async(response)
        finally:
            response.close()

    started = time.perf_counter()
    await asyncio.gather(*(one() for _ in range(count)))
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


def _summary(latencies: list[float], count: int, walls: list[float]) -> dict[str, float | int]:
    median_wall = statistics.median(walls)
    return {
        "requests_per_trial": count,
        "repeats": len(walls),
        "median_wall_seconds": median_wall,
        "requests_per_second": count / median_wall,
        "latency_median_ms": statistics.median(latencies) * 1000,
        "latency_p95_ms": _percentile(latencies, 0.95) * 1000,
        "latency_p99_ms": _percentile(latencies, 0.99) * 1000,
    }


def _throughput_summary(count: int, walls: list[float]) -> dict[str, float | int]:
    median_wall = statistics.median(walls)
    return {
        "requests_per_trial": count,
        "repeats": len(walls),
        "median_wall_seconds": median_wall,
        "requests_per_second": count / median_wall,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrent-requests", type=int, default=256)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--out", default="benchmark-results/http-client.json")
    args = parser.parse_args()

    if min(args.requests, args.concurrent_requests, args.workers, args.repeats) <= 0:
        parser.error("requests, concurrent-requests, workers, and repeats must be positive")
    if args.warmup < 0:
        parser.error("warmup must be non-negative")

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
            "httpx_backend": "httpcore asyncio (async) and httpcore sync (sync)",
            "server": "ThreadingHTTPServer, loopback, HTTP/1.1 keep-alive",
            "payload_bytes": len(BODY),
            "workers_or_connections": args.workers,
            "requests_per_sequential_trial": args.requests,
            "requests_per_concurrent_trial": args.concurrent_requests,
            "repeats": args.repeats,
            "warmup": args.warmup,
            "flpit_async_execution": "FlpIt Task worker pool running blocking urllib3 transport",
        },
        "sequential": {"sync": {}, "async": {}},
        "concurrent": {"sync": {}, "async": {}},
    }

    handler = HttpClientHandler(max_connections_per_host=args.workers)
    flpit_client = HttpClient(handler, base_address=url)
    httpx_client = httpx.Client(limits=limits, timeout=30)
    try:
        # Warm connections and client-side pools before timing.
        for _ in range(args.warmup):
            response = flpit_client.get(path)
            response.close()
            response = httpx_client.get(url)
            response.close()

        sequential_sync: dict[str, Callable[[], tuple[list[float], float]]] = {
            "flpit_http_sync": lambda: _sequential_flpit_sync(flpit_client, path, args.requests),
            "httpx_sync": lambda: _sequential_httpx_sync(httpx_client, url, args.requests),
        }
        for name, runner in sequential_sync.items():
            trials = [runner() for _ in range(args.repeats)]
            all_latencies = [latency for samples, _ in trials for latency in samples]
            walls = [wall for _, wall in trials]
            results["sequential"]["sync"][name] = _summary(all_latencies, args.requests, walls)

        concurrent_sync: dict[str, Callable[[], float]] = {
            "flpit_http_sync": lambda: _concurrent_flpit_sync(
                flpit_client, path, args.concurrent_requests, args.workers
            ),
            "httpx_sync": lambda: _concurrent_httpx_sync(
                httpx_client, url, args.concurrent_requests, args.workers
            ),
        }
        for name, runner in concurrent_sync.items():
            results["concurrent"]["sync"][name] = _throughput_summary(
                args.concurrent_requests, [runner() for _ in range(args.repeats)]
            )

        async def run_async_trials() -> None:
            async with httpx.AsyncClient(limits=limits, timeout=30) as async_client:
                for _ in range(args.warmup):
                    response = await flpit_client.get_async(path)
                    response.close()
                    response = await async_client.get(url)
                    await response.aclose()

                sequential_async: dict[str, Callable[[], Any]] = {
                    "flpit_http_task_async": lambda: _sequential_flpit_async(
                        flpit_client, path, args.requests
                    ),
                    "httpx_async": lambda: _sequential_httpx_async(
                        async_client, url, args.requests
                    ),
                }
                for name, runner in sequential_async.items():
                    trials = [await runner() for _ in range(args.repeats)]
                    all_latencies = [latency for samples, _ in trials for latency in samples]
                    walls = [wall for _, wall in trials]
                    results["sequential"]["async"][name] = _summary(
                        all_latencies, args.requests, walls
                    )

                concurrent_async: dict[str, Callable[[], Any]] = {
                    "flpit_http_task_async": lambda: _concurrent_flpit_async(
                        flpit_client, path, args.concurrent_requests
                    ),
                    "httpx_async": lambda: _concurrent_httpx_async(
                        async_client, url, args.concurrent_requests
                    ),
                }
                for name, runner in concurrent_async.items():
                    walls = [await runner() for _ in range(args.repeats)]
                    results["concurrent"]["async"][name] = _throughput_summary(
                        args.concurrent_requests, walls
                    )

        asyncio.run(run_async_trials())
    finally:
        flpit_client.close()
        httpx_client.close()
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

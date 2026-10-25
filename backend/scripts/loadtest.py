#!/usr/bin/env python3
"""Reproducible load and resource measurement harness for Aéza Sentinel.

Deliberately dependency-free beyond the standard library so it never has to be
installed into a production image. It measures latency percentiles, throughput
and error rates for the real routes, and it can sample container CPU and memory
while a run is in flight.

Usage:
    python backend/scripts/loadtest.py --base-url http://127.0.0.1:8000 \\
        --email analyst@example.com --password "$ANALYST_PASSWORD" --scenario mixed

    # sample the containers while the run is in flight
    python backend/scripts/loadtest.py ... --docker-stats-interval 2
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Sample:
    route: str
    status: int
    seconds: float
    error: str | None = None


@dataclass
class Result:
    samples: list[Sample] = field(default_factory=list)

    def summary(self, label: str) -> dict:
        ok = [s for s in self.samples if s.error is None and s.status < 400]
        failed = [s for s in self.samples if s.error is not None or s.status >= 400]
        latencies = sorted(s.seconds for s in ok)
        total = sum(s.seconds for s in self.samples)

        def pct(p: float) -> float | None:
            if not latencies:
                return None
            index = min(len(latencies) - 1, int(round(p / 100 * (len(latencies) - 1))))
            return round(latencies[index] * 1000, 1)

        return {
            "scenario": label,
            "requests": len(self.samples),
            "ok": len(ok),
            "failed": len(failed),
            "error_rate": round(len(failed) / len(self.samples), 4) if self.samples else 0.0,
            "wall_seconds": round(total, 2),
            "latency_ms": {
                "min": round(min(latencies) * 1000, 1) if latencies else None,
                "p50": pct(50),
                "p95": pct(95),
                "p99": pct(99),
                "max": round(max(latencies) * 1000, 1) if latencies else None,
                "mean": round(statistics.fmean(latencies) * 1000, 1) if latencies else None,
            },
        }


class Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None

    def login(self, email: str, password: str) -> None:
        payload = json.dumps({"email": email, "password": password}).encode()
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/auth/login",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            self.token = json.loads(response.read())["access_token"]

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, float, str | None]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                response.read()
                return response.status, time.perf_counter() - started, None
        except urllib.error.HTTPError as exc:
            exc.read()
            return exc.code, time.perf_counter() - started, None
        except Exception as exc:
            return 0, time.perf_counter() - started, type(exc).__name__


def _one(client: Client, route: str, method: str, path: str, body: dict | None) -> Sample:
    status, seconds, error = client.call(method, path, body)
    return Sample(route=route, status=status, seconds=seconds, error=error)


def run_scenario(
    client: Client, label: str, jobs: list[tuple[str, str, str, dict | None]], concurrency: int, repeats: int
) -> Result:
    """Fire every job ``repeats`` times across ``concurrency`` threads."""

    result = Result()
    plan = jobs * repeats

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for sample in pool.map(lambda job: _one(client, *job), plan):
            result.samples.append(sample)
    return result


class ContainerSampler(threading.Thread):
    """Sample ``docker stats`` while a scenario runs, to attribute CPU and memory."""

    def __init__(self, interval: float):
        super().__init__(daemon=True)
        self.interval = interval
        self.stop_event = threading.Event()
        self.samples: list[dict] = []

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                output = subprocess.run(
                    ["sudo", "docker", "stats", "--no-stream", "--format",
                     "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}"],
                    capture_output=True, text=True, timeout=30,
                ).stdout.strip()
                for line in output.splitlines():
                    name, cpu, mem, mem_pct = (line.split("|") + ["", "", "", ""])[:4]
                    self.samples.append(
                        {"name": name, "cpu_percent": cpu, "mem": mem, "mem_percent": mem_pct}
                    )
            except Exception:
                pass
            self.stop_event.wait(self.interval)

    def stop(self) -> list[dict]:
        self.stop_event.set()
        self.join(timeout=10)
        return self.samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--scenario",
        choices=("health", "read", "mixed", "write", "whatif", "export"),
        default="mixed",
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=25)
    parser.add_argument("--customer-id", type=int, default=1)
    parser.add_argument("--docker-stats-interval", type=float, default=0.0)
    parser.add_argument("--json-out", help="write the result summary as JSON")
    args = parser.parse_args()

    client = Client(args.base_url)
    client.login(args.email, args.password)


    playbook_code = "overdue_renewal"
    status, _, _ = client.call("GET", f"/api/v1/customers/{args.customer_id}/recommendations")
    if status == 200:
        _, _, _ = (0, 0, 0)
        response = urllib.request.Request(
            f"{client.base_url}/api/v1/customers/{args.customer_id}/recommendations",
            headers={"Authorization": f"Bearer {client.token}"},
        )
        with urllib.request.urlopen(response, timeout=30) as handle:
            items = json.loads(handle.read()).get("items", [])
        if items:
            playbook_code = items[0]["code"]

    scenarios = {
        "health": [("health", "GET", "/health", None)],
        "read": [
            ("summary", "GET", "/api/v1/analytics/summary", None),
            ("customers", "GET", "/api/v1/customers?pageSize=25", None),
            ("customer", "GET", f"/api/v1/customers/{args.customer_id}", None),
            ("settings", "GET", "/api/v1/model/settings", None),
        ],
        "mixed": [
            ("summary", "GET", "/api/v1/analytics/summary", None),
            ("customers", "GET", "/api/v1/customers?pageSize=25", None),
            ("customer", "GET", f"/api/v1/customers/{args.customer_id}", None),
            ("priority", "GET", "/api/v1/priority?horizonDays=30", None),
            ("quality", "GET", "/api/v1/quality", None),
            ("recommendations", "GET", f"/api/v1/customers/{args.customer_id}/recommendations", None),
        ],
        "write": [
            ("playbook-status", "PATCH",
             f"/api/v1/customers/{args.customer_id}/recommendations/{playbook_code}",
             {"status": "in_progress"}),
        ],
        "whatif": [
            ("scenario-compare", "POST", "/api/v1/scenarios/compare",
             {"name": "loadtest", "overrides": {"failedRenewalWindowDays": None}}),
        ],
        "export": [("export-csv", "GET", "/api/v1/export/customers.csv", None)],
    }

    jobs = scenarios[args.scenario]
    sampler = None
    if args.docker_stats_interval > 0:
        sampler = ContainerSampler(args.docker_stats_interval)
        sampler.start()

    started = time.perf_counter()
    result = run_scenario(client, args.scenario, jobs, args.concurrency, args.repeats)
    wall = time.perf_counter() - started

    container_samples = sampler.stop() if sampler else []
    summary = result.summary(args.scenario)
    summary["concurrency"] = args.concurrency
    summary["repeats"] = args.repeats
    summary["rps"] = round(len(result.samples) / wall, 2) if wall else None
    summary["per_route"] = {}
    for route in {s.route for s in result.samples}:
        subset = Result([s for s in result.samples if s.route == route])
        summary["per_route"][route] = subset.summary(route)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if container_samples:
        print("\n# container samples (best-effort)")
        print(json.dumps(container_samples[-12:], ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

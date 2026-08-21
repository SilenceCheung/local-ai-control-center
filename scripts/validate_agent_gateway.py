#!/usr/bin/env python3
"""Repeatable mixed-protocol gateway soak for a loaded local runtime."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="Qwen3.8-27B-4bit")
    parser.add_argument("--calls", type=int, default=30)
    args = parser.parse_args()
    if args.calls < 3:
        parser.error("--calls must be at least 3")

    rows: list[dict[str, object]] = []
    with httpx.Client(
        timeout=120,
        headers={"user-agent": "localai-production-soak/1.0"},
    ) as client:
        for index in range(args.calls):
            dialect = ("chat", "responses", "anthropic")[index % 3]
            started = time.perf_counter()
            if dialect == "chat":
                response = client.post(args.base + "/chat/completions", json={
                    "model": args.model,
                    "messages": [{"role": "user", "content": "Reply exactly OK."}],
                    "max_tokens": 8,
                })
            elif dialect == "responses":
                response = client.post(args.base + "/responses", json={
                    "model": args.model,
                    "input": "Reply exactly OK.",
                    "max_output_tokens": 8,
                })
            else:
                response = client.post(
                    args.base + "/messages",
                    headers={"anthropic-version": "2023-06-01"},
                    json={
                        "model": args.model,
                        "messages": [{"role": "user", "content": "Reply exactly OK."}],
                        "max_tokens": 8,
                    },
                )
            elapsed_ms = (time.perf_counter() - started) * 1000
            rows.append({
                "dialect": dialect,
                "elapsed_ms": elapsed_ms,
                "status": response.status_code,
                "ok": response.status_code == 200 and "OK" in response.text.upper(),
                "request_id": response.headers.get("x-localai-request-id"),
            })

    timings = sorted(float(row["elapsed_ms"]) for row in rows)
    failures = [row for row in rows if not row["ok"]]
    summary = {
        "calls": len(rows),
        "success": len(rows) - len(failures),
        "failures": failures,
        "p50_ms": round(statistics.median(timings), 1),
        "p95_ms": round(timings[max(0, int(len(timings) * 0.95) - 1)], 1),
        "max_ms": round(max(timings), 1),
        "request_ids_unique": len({row["request_id"] for row in rows if row["request_id"]}),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

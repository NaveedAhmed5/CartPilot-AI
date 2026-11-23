#!/usr/bin/env python3
"""Run tests.json against a CartPilot API and print a benchmark table.

    python scripts/benchmark.py --base-url https://<your-space>.hf.space
    python scripts/benchmark.py --base-url http://localhost:8000 --update-readme

Uses only the Python standard library. Each run uses fresh user/thread ids, so it
can be repeated against the same database. Costs are estimated with Claude Haiku 5.5
list prices ($0.10 / $0.50 per million input / output tokens); prompt-cache reads
are cheaper, so the real bill is lower.
"""

import argparse
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRICE_IN, PRICE_OUT = 0.10, 0.50
README_START, README_END = "<!-- BENCHMARK:START -->", "<!-- BENCHMARK:END -->"


def post_chat(base: str, payload: dict, timeout: float) -> tuple[dict, float, int]:
    req = urllib.request.Request(
        f"{base}/chat", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
            status = r.status
    except urllib.error.HTTPError as e:
        body, status = {"reply": e.read().decode()[:300], "tool_calls": [], "tokens": {"in": 0, "out": 0}}, e.code
    except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
        body, status = {"reply": f"request failed: {e}", "tool_calls": [], "tokens": {"in": 0, "out": 0}}, 0
    return body, time.perf_counter() - t0, status


def contains(reply: str, needle: str) -> bool:
    reply = reply.replace("\u202f", " ").replace("\u00a0", " ").replace("\u2011", "-")
    if len(needle) <= 2:  # short tokens like "L" must match as a whole word
        return re.search(rf"\b{re.escape(needle)}\b", reply) is not None
    return needle.lower() in reply.lower()


def check(expect: dict, body: dict, status: int) -> list[str]:
    problems = []
    if status != 200:
        return [f"HTTP {status}" if status else body.get("reply", "request failed")]
    if not {"reply", "tool_calls", "tokens"} <= set(body):
        problems.append("response missing reply/tool_calls/tokens")
    reply = body.get("reply", "")
    tools = [t.get("name") for t in body.get("tool_calls", [])]
    for t in expect.get("tools_called", []):
        if t not in tools:
            problems.append(f"expected tool {t}, got {tools or 'none'}")
    if expect.get("tools_called_any") and not set(expect["tools_called_any"]) & set(tools):
        problems.append(f"expected one of {expect['tools_called_any']}, got {tools or 'none'}")
    for t in expect.get("tools_not_called", []):
        if t in tools:
            problems.append(f"tool {t} must not be called")
    if expect.get("tools_called_none") and tools:
        problems.append(f"expected no tools, got {tools}")
    if expect.get("reply_contains_any") and not any(contains(reply, n) for n in expect["reply_contains_any"]):
        problems.append(f"reply lacks any of {expect['reply_contains_any']}")
    for group in expect.get("reply_contains_all_any", []):
        if not any(contains(reply, n) for n in group):
            problems.append(f"reply lacks any of {group}")
    for n in expect.get("reply_not_contains", []):
        if n.lower() in reply.lower():
            problems.append(f"reply must not contain '{n}'")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--tests", default=str(ROOT / "tests.json"))
    ap.add_argument("--timeout", type=float, default=90)
    ap.add_argument("--label", default="", help="e.g. 'claude-haiku-5-5 on HF Spaces'")
    ap.add_argument("--update-readme", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--pause", type=float, default=0, help="seconds to wait between turns")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    try:
        with urllib.request.urlopen(f"{base}/health", timeout=30) as r:
            health = r.read().decode().strip()
    except Exception as e:
        print(f"/health failed: {e}")
        return 2
    print(f"/health -> {health!r}")

    run = uuid.uuid4().hex[:6]
    suite = json.loads(Path(args.tests).read_text())
    rows, latencies, total_in, total_out = [], [], 0, 0
    for case in suite["cases"]:
        case_ok, case_problems, case_lat, case_in, case_out, case_tools = True, [], 0.0, 0, 0, []
        for step in case["steps"]:
            payload = {k: step[k].replace("{run}", run) for k in ("user_id", "thread_id", "message")}
            if args.pause:
                time.sleep(args.pause)
            body, latency, status = post_chat(base, payload, args.timeout)
            problems = check(step.get("expect", {}), body, status)
            tokens = body.get("tokens", {}) or {}
            case_lat += latency
            latencies.append(latency)
            case_in += int(tokens.get("in", 0))
            case_out += int(tokens.get("out", 0))
            case_tools += [t.get("name") for t in body.get("tool_calls", [])]
            if problems:
                case_ok = False
                case_problems += problems
            if args.verbose:
                print(f"  [{case['id']}] {payload['message'][:60]!r}\n    -> {body.get('reply', '')[:200]!r}\n    tools={case_tools} {problems or ''}")
        total_in += case_in
        total_out += case_out
        rows.append({
            "id": case["id"], "category": case["category"], "name": case["name"], "pass": case_ok,
            "latency": case_lat, "tokens_in": case_in, "tokens_out": case_out,
            "tools": sorted(set(case_tools)), "problems": case_problems,
        })
        print(f"{case['id']} {'PASS' if case_ok else 'FAIL'} {case['name']} ({case_lat:.1f}s) {'; '.join(case_problems)}")

    passed = sum(r["pass"] for r in rows)
    cost = total_in / 1e6 * PRICE_IN + total_out / 1e6 * PRICE_OUT
    p50 = statistics.median(latencies) if latencies else 0
    p95 = sorted(latencies)[max(0, int(round(0.95 * len(latencies))) - 1)] if latencies else 0
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    label = args.label or base

    lines = [
        f"Run: {when}, target: {label}",
        "",
        "| # | Category | Test | Result | Latency | Tokens in / out | Tools used |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['category']} | {r['name']} | {'✅ pass' if r['pass'] else '❌ fail'} | "
            f"{r['latency']:.1f} s | {r['tokens_in']:,} / {r['tokens_out']:,} | {', '.join(r['tools']) or '—'} |"
        )
    lines += [
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Tests passed | **{passed} / {len(rows)}** |",
        f"| Median latency per turn | {p50:.1f} s |",
        f"| p95 latency per turn | {p95:.1f} s |",
        f"| Total tokens (in / out) | {total_in:,} / {total_out:,} |",
        f"| Estimated cost for the whole suite (Haiku 5.5 list price) | ${cost:.4f} |",
        f"| Safety-blocked turns that used 0 tokens | {sum(1 for r in rows if r['category'].startswith('safety') and r['tokens_in'] == 0)} |",
    ]
    table = "\n".join(lines)
    print("\n" + table)
    out = ROOT / "docs" / "benchmark.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("# Benchmark results\n\n" + table + "\n")
    if args.update_readme:
        readme = ROOT / "README.md"
        text = readme.read_text()
        if README_START in text and README_END in text:
            pre, rest = text.split(README_START, 1)
            _, post = rest.split(README_END, 1)
            readme.write_text(f"{pre}{README_START}\n{table}\n{README_END}{post}")
            print("README benchmark section updated.")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Отчёт нагрузочного теста из CSV locust → docs/perf/report.md.

uv run python scripts/perf_report.py load/reports/run_stats.csv docs/perf/report.md
"""

import csv
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

TARGET_P95_MS = 150
TARGET_RPS = 500


def machine() -> str:
    cpus = os.cpu_count()
    memory = ""
    if sys.platform == "darwin":
        out = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        if out.stdout.strip().isdigit():
            memory = f", {int(out.stdout) // 1024**3} GB RAM"
    return f"{platform.system()} {platform.machine()}, {cpus} CPU{memory}"


def main(stats_csv: str, output: str) -> None:
    rows = list(csv.DictReader(Path(stats_csv).open()))
    lines = [
        "# Load test report",
        "",
        f"- Date: {datetime.now(UTC):%Y-%m-%d %H:%M UTC}",
        f"- Machine: {machine()} (local Docker stack, all services on one host)",
        "- Profile: 80% search, 15% product card (gRPC), 5% checkout; through Nginx → api-gateway",
        f"- Target (TZ): p95 ≤ {TARGET_P95_MS} ms at {TARGET_RPS} RPS",
        "",
        "| Request | Count | Failures | RPS | p50, ms | p95, ms | p99, ms |",
        "|---------|------:|---------:|----:|--------:|--------:|--------:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['Name']} | {row['Request Count']} | {row['Failure Count']} | "
            f"{float(row['Requests/s']):.1f} | {row['50%']} | {row['95%']} | {row['99%']} |"
        )
    total = next(r for r in rows if r["Name"] == "Aggregated")
    p95, rps = float(total["95%"]), float(total["Requests/s"])
    verdict = "met" if p95 <= TARGET_P95_MS and rps >= TARGET_RPS * 0.95 else "not met"
    lines += [
        "",
        f"**Result: target {verdict}** — p95 {p95:.0f} ms at {rps:.0f} RPS.",
        "",
        "RPS is averaged over the whole run, including the ramp-up of virtual users.",
        "Search requests dominate the profile and have the highest latency; they are the",
        "first place to optimise (e.g. caching popular queries) if the target slips.",
        "",
    ]
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

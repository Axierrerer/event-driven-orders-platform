# Load test report

- Date: 2026-10-09 21:13 UTC
- Machine: Darwin arm64, 12 CPU, 24 GB RAM (local Docker stack, all services on one host)
- Profile: 80% search, 15% product card (gRPC), 5% checkout; through Nginx → api-gateway
- Target (TZ): p95 ≤ 150 ms at 500 RPS

| Request | Count | Failures | RPS | p50, ms | p95, ms | p99, ms |
|---------|------:|---------:|----:|--------:|--------:|--------:|
| GET /products/{id} | 4259 | 0 | 72.1 | 34 | 80 | 100 |
| GET /products?q= | 22808 | 0 | 386.1 | 79 | 150 | 200 |
| POST /orders | 1387 | 0 | 23.5 | 59 | 110 | 140 |
| Aggregated | 28454 | 0 | 481.7 | 72 | 140 | 190 |

**Result: target met** — p95 140 ms at 482 RPS.

RPS is averaged over the whole run, including the ramp-up of virtual users.
Search requests dominate the profile and have the highest latency; they are the
first place to optimise (e.g. caching popular queries) if the target slips.

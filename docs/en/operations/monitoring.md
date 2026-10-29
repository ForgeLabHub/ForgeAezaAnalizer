# Monitoring

English version of [../../operations/monitoring.md](../../operations/monitoring.md).

| Signal | Where | Purpose |
| --- | --- | --- |
| `/health` | api | liveness, used by the image HEALTHCHECK |
| `/metrics` | api, requires `AEZA_METRICS_TOKEN` | latency and codes per route (`backend/app/metrics.py`) |
| Structured logs | container stdout | incident analysis |
| Snapshot provenance | `domain/provenance.py` | understand which data produced a number |
| Model state | `/api/v1/model/*` | availability of the LLM provider |

## Minimal alerts

1. `/health` does not answer for 2 minutes.
2. The 5xx share is above 1% over 5 minutes.
3. `/metrics` is unreachable or the token is not set in production.
4. The snapshot has not been refreshed for longer than expected
   (`AEZA_SNAPSHOT_POLL_SECONDS`).
5. LLM provider errors with `AEZA_AI_ENABLED=1` — feature degradation, not a service
   outage.

## What is missing

- No distributed tracing: one service, but background recalculations
  (`AEZA_RECALCULATE_SECONDS`) are not linked to requests.
- No SLO expressed as a number.
- No out-of-the-box alerts — metrics are exposed, the rules belong to operations.

# Candidate-first external data refresh

The daily sidecar refreshes external data in two passes:

1. Active entry candidates, the top current leaders, and portfolio positions are written to a temporary priority universe and refreshed first.
2. The wider universe is backfilled incrementally after the priority pass.

This prevents the bounded external-data budget from being consumed alphabetically before actionable names receive earnings and revision coverage. Missing external fields remain nullable and do not stop the core build. The encrypted dashboard and encrypted operational state remain the only persisted private outputs.

# Sidecar failure guards

The sidecar intentionally separates expensive I/O from deterministic scoring.

Execution order:
1. restore caches
2. ensure and immediately persist price cache
3. run the full deterministic scoring pipeline
4. refresh optional external data
5. build operational outputs
6. validate contracts and quality gates
7. push with rebase/retry and no force push

Missing SEC fundamentals are nullable and must never change a column from a Series into a scalar. Optional external-data failures remain warnings; missing QQQ, low price coverage, zero candidates, malformed generated contracts, and real git conflicts remain hard failures.

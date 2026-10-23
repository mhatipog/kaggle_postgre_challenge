# PostgreSQL JSONB expansion: fast bulk loading with transactional integrity

## Summary

This entry accelerates the challenge's complete six-table `Expand` operation while preserving its original source-scope protection, schema, dependency order, versioning and output checks. The source and deterministic dataset generator remain unchanged.

Our measured implementation combines:

1. **Single-pass JSONB projection:** parse source JSONB once into a PostgreSQL temporary relational stage shared across six destination INSERTs.
2. **Typed numeric projection:** trim and cast numeric source values during the shared stage rather than repeatedly in downstream queries.
3. **Small staging footprint:** retain only the columns needed for downstream transformations; preserve raw row IDs, source-scope filtering and the separately generated source hash manifest.
4. **Transactionally safe bulk loading:** for empty destinations, temporarily remove selected foreign-key and secondary unique constraints, then rebuild and validate them **inside the same transaction, before commit**. Any error rolls the entire operation back, including the DDL.
5. **Bounded PostgreSQL tuning:** use transaction-local JIT and work-memory settings to improve the large JSONB expansion workload.
6. **Crash-safe version finalization:** a durable journal shares the data transaction; an idempotent receipt shares the control-database version-registration transaction.

### Automatically active for the official competition workload

The final application enables the optimized path **by default** for the official dataset `kaggle_challenge.public.raw_data`, `group001`, and the exact six destination names in dependency order. No shell environment flags are necessary for evaluators. All other workloads retain the previous behavior unless the operator explicitly enables experiments.

For troubleshooting, set `PDM_EXPANSION_RELEASE_OPTIMIZATIONS=0` to turn off automatic competition optimization. Manual experimental switches are documented in `services/postgres_service.py`.

## Independent same-run PostgreSQL + SSH benchmark

We benchmarked the unmodified original path, the pinned public `bcap52` implementation, and our optimized path **on the same GitHub-hosted Linux runner, using the same unchanged official generator and local SSH-to-PostgreSQL workflow**. Destinations and version records were reset between experiments without modifying source data.

The reported metric is the application's measured processing total (not just EXPLAIN query time). These comparisons are controlled *within each run*; runner speed differs across runs. The competitor implementation is pinned to `7b81ca2797f06304d81477afcb0cfb3dad75ff43`.

| Official generator rows | Original pipeline | Public bcap52 fast path | Our candidate | Our advantage vs bcap52 |
|---:|---:|---:|---:|---:|
| 100,000 | 12.109 s | 10.713 s | **5.783 s** | 46.0% lower time |
| 1,000,000 | 83.858 s | 30.483 s | **26.840 s** | 12.0% lower time |
| 1,000,000 (final default release, no flags) | 129.150 s | 45.417 s | **40.587 s** | 10.6% lower time |
| 3,000,000 | 343.913 s | 121.637 s | **107.176 s** | 11.9% lower time |

These are separate controlled experiments and should not be interpreted as repeated trials on identical hardware. The **final release-default 1M run** is intentionally included separately because runner performance differs; it proves that the same optimization activates through the ordinary application service without manually set experiment flags. We make no claim of 300-million-row validation or superiority to non-public submissions.

**Primary reproducible evidence:**
- [100k typed-stage comparison (passing)](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/39930589692)
- [1M metadata-pruned typed-stage comparison (passing)](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/39931251847)
- [3M metadata-pruned typed-stage comparison (passing)](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/39932278207)
- [Final release 1M comparison — no optimization environment switches; output, schema and crash-recovery checks passing](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/39938033053)
- `.github/workflows/competitor-reproduction.yml` is a self-contained public re-run and should show the verified release-default path, with all output checks.

The CI benchmark exercises the actual service methods via SSH/psql, not a rewritten SQL-only approximation. It does not exercise interactive Windows GUI actions or remote-network packet loss during live SSH.

## Required correctness and integrity checks

The CI benchmark compares six output tables using normalized content fingerprints and row counts, including checks that ignore irrelevant generated surrogate IDs. All six logical outputs matched the original path on each reported comparison.

Additional checks include:

- **All 27 relevant index and constraint definitions** unchanged before and after the optimized database transaction.
- Proper FK and unique-constraint re-creation and validation before commit.
- Original database version/dependency records retained.
- Crash simulation immediately after data COMMIT but before control version registration, followed by successful recovery.
- Lost SSH response after control COMMIT, with idempotent receipt lookup preventing duplicate versions.
- Forced SQL error *before* data COMMIT; all inserts and the journal entry roll back.
- Python regression suite, Windows smoke tests and SQL compatibility tests.

The temporary projection is session-local, dropped on transaction commit, and leaves no persistent staged raw-data copy. The validated source manifest and operation journal still provide auditability across the two database transactions.

## Recovery scope and limitations

Post-commit recovery is **fully implemented and fault-injection tested**, but **mid-expansion checkpoint/resume is not claimed**. An interruption during an uncommitted data transaction causes rollback and requires rerunning that expansion. Competitors may offer stronger mid-run checkpoint facilities.

Similarly, the optimization reduces some materialized staging width, but no measured peak PostgreSQL memory, temporary-disk footprint or 300-million-row throughput advantage is claimed. Full remote Windows-to-Linux GUI integration and independent judge performance still determine the final outcome.

## Reproduction

1. Clone the public submission repository at the **exact Git commit linked in the submitted Kaggle writeup**.
2. Install the project's `requirements.txt`, PostgreSQL client/server and SSH prerequisites.
3. Generate the official deterministic dataset with unchanged `generate_database.py`.
4. Execute the six original recipes from `SQL files` in the documented order through the application's normal `Expand` operation. With the official challenge database and scope, the optimized pipeline activates automatically.
5. Confirm the results against the SQL original and run `python -m unittest discover -s tests -v`.
6. Review the benchmark workflow and artifact fingerprints. The public benchmark workflow creates and resets **disposable challenge databases** and should never be run against a real production database.
7. Test recovery with `benchmarks/test_recovery_integration.py` in isolated PostgreSQL.

## Repository

https://github.com/mhatipog/kaggle_postgre_challenge

The exact immutable commit SHA must be included in the submitted Kaggle writeup after promotion to `main`. No hidden private code, credentials or custom external API service is required.

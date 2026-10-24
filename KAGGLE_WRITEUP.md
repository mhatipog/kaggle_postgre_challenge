# PostgreSQL JSONB expansion: faster bulk loading with transactional integrity

## Summary

This entry accelerates the challenge's complete six-table `Expand` operation while preserving its original source-scope protection, schema, dependency order, versioning and output checks. The source and deterministic dataset generator remain unchanged.

**Validated implementation commit:** `d892fa252b49bc9214093415f09db37832f24b47` (PR #16 and PR #17 promoted to `main` on 24 October 2026). This is the implementation merge commit; subsequent documentation-only commits do not change the measured application code.

Our measured implementation combines:

1. **Single-pass JSONB projection:** parse source JSONB once into a PostgreSQL temporary relational stage shared across the six destination INSERTs.
2. **Typed numeric projection:** trim and cast numeric source values during that shared stage.
3. **Reduced staging width:** retain the fields needed for transformations, source-scope filtering and the validated dependency manifest.
4. **Stage-backed dependency manifest:** build the source dependency manifest from the already-projected stage rather than rescanning the original raw source. Equality to the original raw-data aggregation is explicitly checked.
5. **Transactionally safe bulk loading:** for the narrowly gated, empty-destination challenge workload, temporarily remove selected primary-key, foreign-key and secondary unique constraints/indexes and rebuild/validate the original definitions **inside the same database transaction before commit**. Any error rolls back the DDL and data changes.
6. **Bounded PostgreSQL tuning:** use transaction-local JIT and work-memory settings.
7. **Crash-safe version finalization:** a durable journal shares the data transaction; an idempotent receipt shares the control-database version-registration transaction.

### Automatically active for the official competition workload

The validated combined optimization is active **without environment flags** for the exact official dataset `kaggle_challenge.public.raw_data`, `group001`, and the six expected destinations in dependency order, when the relevant empty-destination preconditions hold. Other workloads retain the normal behavior unless explicitly opted in. For diagnosis, `PDM_EXPANSION_RELEASE_OPTIMIZATIONS=0` disables the release fast path; `PDM_EXPANSION_MANIFEST_FROM_STAGE=0` and `PDM_EXPANSION_REBUILD_PRIMARY_KEYS=0` independently disable the two new features. See `services/postgres_service.py` for details.

## Benchmark methodology and measured results

We exercised the real application's six-table `Expand` workflow through SSH/psql against local PostgreSQL on GitHub-hosted Linux runners, using the **unchanged official deterministic generator**. The original SQL recipes, input data and source scope were not modified. Destination tables and version state were reset between arms of each controlled comparison. Times below are the application's **measured processing totals**, not SQL-only EXPLAIN timings, end-user GUI wall-clock time or independent Kaggle judging results.

The public comparison implementation from `bcap52` is pinned to `7b81ca2797f06304d81477afcb0cfb3dad75ff43`. Comparisons **within the same workflow run** are meaningful; hosted-runner performance differs between runs. Percentages are reductions in processing time, not throughput multipliers.

### New combined default release — controlled same-run comparisons (24 October 2026)

| Generated source rows | Combined default candidate | Previous release | Pinned bcap52 | Time saved vs previous release | Time saved vs bcap52 |
|---:|---:|---:|---:|---:|---:|
| 1,000,000 — default-on, no flags | **36.388 s** | 40.789 s | 47.891 s | **10.79%** | **24.02%** |
| 1,000,000 — independent A/B | **38.494 s** | 38.948 s | 48.427 s | **1.17%** | **20.51%** |
| 10,000,000 — candidate-first A/B | **361.786 s** | 446.543 s | 449.588 s | **18.98%** | **19.53%** |
| 10,000,000 — reversed-order A/B | **396.554 s** | 443.800 s | 459.083 s | **10.65%** | **13.62%** |
| 30,000,000 — scale/parity gate | **1,249.439 s** | 1,524.376 s | Not measured | **18.04%** | Not claimed |

The two 10M run orders agree on the direction of improvement, but differ in absolute times. The combined candidate was **not** fastest among all internal configurations at 1M: the PK-only arm measured 35.763 s in the default-on run, versus 36.388 s combined. At 10M, the combined arm beat both individual arms in each reported A/B run. The 30M gate compared the new candidate with our previous release, **not** with bcap52 or the original unmodified pipeline.

### Earlier release — comparison with the unmodified original pipeline

The following measurements were taken for the **previous submitted implementation**, before the new manifest/PK combination was promoted. They establish a controlled baseline against the unmodified original, but must **not** be misrepresented as timings for the newly promoted combined candidate.

| Generated source rows | Unmodified original | Pinned bcap52 | Earlier submitted implementation | Earlier implementation speedup vs original |
|---:|---:|---:|---:|---:|
| 100,000 | 12.109 s | 10.713 s | **5.783 s** | **2.09×** |
| 1,000,000 | 83.858 s | 30.483 s | **26.840 s** | **3.12×** |
| 3,000,000 | 343.913 s | 121.637 s | **107.176 s** | **3.21×** |

### Reproducible CI evidence

- [Combined default-on 1M benchmark, six-table parity, original 27 definitions, manifest parity and recovery — PASS](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/40089706248)
- [Independent combined 1M A/B — PASS](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/40089706184)
- [Combined 10M A/B, candidate first, including recovery — PASS](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/40089706193)
- [Combined 10M reversed-order A/B, including recovery — PASS](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/40089706224)
- [Combined 30M scale gate and output parity — PASS](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/40089706225)
- [Python compatibility on combined release head — PASS](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/40089706219)
- [SQL regression checks on combined research head — PASS](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/40088983305)
- [Windows smoke tests on combined research head — PASS](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/40088983256)
- [Earlier 3M original/bcap52/previous-release comparison — PASS](https://github.com/mhatipog/kaggle_postgre_challenge/actions/runs/39932278207)

The CI benchmarks exercise the actual application service methods through SSH/psql rather than substituting an approximate SQL-only query. Logs and public workflow definitions allow independent inspection. We make **no claim** of 300M-row validation, peak-memory superiority, a bcap52 comparison at 30M, or official first place.

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

The temporary projection is session-local, dropped on transaction commit, and leaves no persistent staged raw-data copy. The validated stage-backed source manifest and operation journal still provide auditability across the two database transactions.

## Recovery scope and limitations

Post-commit recovery is **fully implemented and fault-injection tested**, but **mid-expansion checkpoint/resume is not claimed**. An interruption during an uncommitted data transaction causes rollback and requires rerunning that expansion. Competitors may offer stronger mid-run checkpoint facilities.

Similarly, the optimization reduces some materialized staging width, but no measured peak PostgreSQL memory, temporary-disk footprint or 300-million-row throughput advantage is claimed. Full remote Windows-to-Linux GUI integration and independent judge performance still determine the final outcome.

## Reproduction

1. Clone the public submission repository at the **exact Git commit linked in the submitted Kaggle writeup** (the validated implementation merge is `d892fa252b49bc9214093415f09db37832f24b47`; later documentation commits retain the same application code).
2. Install the project's `requirements.txt`, PostgreSQL client/server and SSH prerequisites.
3. Generate the official deterministic dataset with unchanged `generate_database.py`.
4. Execute the six original recipes from `SQL files` in the documented order through the application's normal `Expand` operation. With the official challenge database and scope, the optimized pipeline activates automatically.
5. Confirm the results against the SQL original and run `python -m unittest discover -s tests -v`.
6. Review the benchmark workflow and artifact fingerprints. The public benchmark workflow creates and resets **disposable challenge databases** and should never be run against a real production database.
7. Test recovery with `benchmarks/test_recovery_integration.py` in isolated PostgreSQL.

## Repository

https://github.com/mhatipog/kaggle_postgre_challenge

The validated implementation merge commit is `d892fa252b49bc9214093415f09db37832f24b47`. For the final Kaggle website submission, link the exact immutable public `main` commit used for publication, which may be a later documentation-only commit. No hidden private code, credentials or custom external API service is required.

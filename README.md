# BSD Workers

Ephemeral SageMath workers for the BSD project. The repository is intentionally public so standard GitHub-hosted Actions runners do not consume paid Actions minutes.

## Architecture

- One workflow run accepts up to **30 independent tasks**.
- GitHub Actions fans them out with a matrix and `max-parallel: 30`.
- Each task runs in the official `sagemath/sagemath:latest` Docker image.
- Each worker has a hard workflow timeout of **120 minutes**.
- Every task produces a JSON artifact named `bsd-result-<task-id>`.
- `fail-fast` is disabled: one failed computation does not cancel the other workers.
- The intended controller is `bsd_lab_controller_v3`: it should dispatch batches through GitHub `repository_dispatch` and collect the resulting artifacts. This extends the existing controller; it does not create a second scheduler.

Actual simultaneous execution is still subject to GitHub's concurrency limit for the account. A 30-task batch therefore creates 30 worker jobs; if GitHub grants fewer than 30 simultaneous hosted runners, the rest queue automatically.

## Dispatch payload

Event type: `bsd_tasks`

```json
{
  "event_type": "bsd_tasks",
  "client_payload": {
    "tasks": [
      {"id": "prime-1", "type": "prime_test", "params": {"n": "27556875248067978887984387004542711"}},
      {"id": "factor-1", "type": "factor_integer", "params": {"n": "2026"}},
      {"id": "curve-1", "type": "ec_summary", "params": {"label": "3954c1", "operations": ["rank_bounds", "torsion_order", "root_number"]}},
      {"id": "ff-1", "type": "finite_field_point_count", "params": {"p": 101, "a_invariants": [0, -1, 1, -10, -20]}}
    ]
  }
}
```

The `tasks` array may contain 1–30 items.

## Supported tasks

- `self_test`
- `prime_test` — parameter: `n`
- `factor_integer` — parameter: `n`
- `ec_summary` — `label` or `a_invariants`; optional `operations`
- `finite_field_point_count` — parameters: prime `p`, `a_invariants`

`ec_summary.operations` supports `a_invariants`, `discriminant`, `conductor`, `torsion_order`, `rank_bounds`, `rank`, `root_number`, and `analytic_rank`.

## Result envelope

Each artifact contains JSON with task id/type, worker slot, GitHub run id, timestamps, duration, success flag, and either `result` or a structured error with traceback.

## Manual test

The workflow also supports `workflow_dispatch`. Leaving its default payload runs one SageMath self-test.

# BSD Workers

Free / no-cost worker pool for the BSD project, designed to extend the existing `bsd_lab_controller_v3` rather than replace it with another scheduler.

## Providers

| Provider | Integration in this repo | State |
| --- | --- | --- |
| GitHub Actions | `.github/workflows/bsd-worker.yml` | **Active and tested** |
| CircleCI | `.circleci/config.yml` | Configured; external CircleCI project authorization still required |
| GitLab CI | `.gitlab-ci.yml` | Configured; GitLab project/mirror authorization still required |
| Oracle Always Free | `oracle/` Terraform + SSH worker | Fully prepared; OCI account credentials and `terraform apply` still required |

The repository contains no provider tokens, OCI credentials, SSH private keys, or other secrets.

## GitHub Actions

One workflow run accepts up to **30 independent tasks** and fans them out with a matrix using `max-parallel: 30`. Each worker runs in SageMath, has a 120-minute timeout, uploads a JSON result artifact, and uses `fail-fast: false` so one failed computation does not cancel the others.

Actual simultaneous execution is controlled by GitHub's account concurrency limit. Excess jobs queue automatically.

Event type for automated dispatch: `bsd_tasks`.

```json
{
  "event_type": "bsd_tasks",
  "client_payload": {
    "tasks": [
      {"id": "prime-1", "type": "prime_test", "params": {"n": "27556875248067978887984387004542711"}},
      {"id": "factor-1", "type": "factor_integer", "params": {"n": "2026"}},
      {"id": "curve-1", "type": "ec_summary", "params": {"label": "3954c1", "operations": ["rank_bounds", "torsion_order", "root_number"]}}
    ]
  }
}
```

## CircleCI

`.circleci/config.yml` uses a parameterized parallel SageMath job. The controller sends:

- `workers`: number of tasks / workers to request
- `tasks_b64`: base64-encoded JSON task array

`ci_entrypoint.py` maps `CIRCLE_NODE_INDEX` to exactly one BSD task, so workers do not duplicate work. Results are stored as CircleCI artifacts.

`provider_dispatch.py circleci tasks.json` is the controller-side API adapter. It expects:

```text
BSD_CIRCLECI_TOKEN
BSD_CIRCLECI_PROJECT_SLUG
BSD_CIRCLECI_BRANCH=main
```

## GitLab CI

`.gitlab-ci.yml` uses typed pipeline inputs and sets `parallel` dynamically from the requested worker count. Push pipelines are disabled so a mirrored repository does not burn the free compute allowance just because GitHub receives a commit.

`provider_dispatch.py gitlab tasks.json` expects:

```text
BSD_GITLAB_TOKEN
BSD_GITLAB_PROJECT
BSD_GITLAB_REF=main
```

The GitLab project value can be a numeric project ID or URL-encoded project path accepted by the API.

## Oracle Always Free

`oracle/` defines two persistent `VM.Standard.A1.Flex` ARM workers, each 1 OCPU / 6 GB RAM, for a combined 2 OCPUs / 12 GB. SageMath is installed through conda-forge because the official SageMath Docker image is currently amd64-only.

Terraform creates the network, public subnet, SSH access, two VMs, and cloud-init bootstrap. See `oracle/README.md`.

Once the two VM IPs exist, `oracle_dispatch.py` can feed them tasks over SSH in parallel using:

```text
BSD_ORACLE_HOSTS=<ip1>,<ip2>
BSD_ORACLE_SSH_KEY=<private-key-path>
BSD_ORACLE_SSH_USER=ubuntu
```

## Common task format

All providers use the same task objects and the same `worker.py` implementation.

Supported task types:

- `self_test`
- `prime_test` — parameter `n`
- `factor_integer` — parameter `n`
- `ec_summary` — `label` or `a_invariants`; optional `operations`
- `finite_field_point_count` — prime `p` and `a_invariants`

`ec_summary.operations` supports `a_invariants`, `discriminant`, `conductor`, `torsion_order`, `rank_bounds`, `rank`, `root_number`, and `analytic_rank`.

Each result envelope contains task id/type, worker identity, provider/run metadata when available, timestamps, duration, success flag, and either a result or structured error.

## Controller integration

`provider_dispatch.py` provides API adapters for GitHub, CircleCI, and GitLab. `oracle_dispatch.py` handles the two persistent OCI machines via SSH.

The intended production path remains:

`lab_enqueue -> SQLite work_queue -> BSD Lab Controller -> provider adapter -> worker -> result`

This preserves the existing persistent queue and deduplication model instead of creating a competing scheduler.

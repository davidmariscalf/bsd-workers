#!/usr/bin/env python3
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from sage.all import EllipticCurve, GF, ZZ, factor, is_prime
from sage.env import SAGE_VERSION


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    try:
        return int(value)
    except Exception:
        return str(value)


def _curve(params, field=None):
    if "a_invariants" in params:
        ainvs = params["a_invariants"]
        return EllipticCurve(field, ainvs) if field is not None else EllipticCurve(ainvs)
    if field is None and "label" in params:
        return EllipticCurve(str(params["label"]))
    raise ValueError("Provide a_invariants (or label for curves over Q)")


def task_self_test(params):
    e = EllipticCurve([0, -1, 1, -10, -20])
    return {
        "sage_version": SAGE_VERSION,
        "factor_2026": [[int(p), int(k)] for p, k in factor(ZZ(2026))],
        "curve_discriminant": int(e.discriminant()),
        "curve_conductor": int(e.conductor()),
    }


def task_prime_test(params):
    n = ZZ(params["n"])
    return {"n": str(n), "is_prime": bool(is_prime(n))}


def task_factor_integer(params):
    n = ZZ(params["n"])
    f = factor(n)
    return {
        "n": str(n),
        "factors": [[str(p), int(k)] for p, k in f],
    }


def task_ec_summary(params):
    e = _curve(params)
    operations = params.get(
        "operations",
        ["a_invariants", "discriminant", "conductor", "torsion_order", "rank_bounds", "root_number"],
    )
    out = {}
    for op in operations:
        if op == "a_invariants":
            out[op] = [str(x) for x in e.a_invariants()]
        elif op == "discriminant":
            out[op] = str(e.discriminant())
        elif op == "conductor":
            out[op] = str(e.conductor())
        elif op == "torsion_order":
            out[op] = int(e.torsion_subgroup().order())
        elif op == "rank_bounds":
            out[op] = [int(x) for x in e.rank_bounds()]
        elif op == "rank":
            out[op] = int(e.rank())
        elif op == "root_number":
            out[op] = int(e.root_number())
        elif op == "analytic_rank":
            out[op] = int(e.analytic_rank())
        else:
            raise ValueError(f"Unsupported ec_summary operation: {op}")
    return out


def task_finite_field_point_count(params):
    p = ZZ(params["p"])
    if not is_prime(p):
        raise ValueError("p must be prime")
    e = _curve(params, GF(p))
    return {
        "p": str(p),
        "cardinality": str(e.cardinality()),
        "trace_of_frobenius": str(e.trace_of_frobenius()),
    }


HANDLERS = {
    "self_test": task_self_test,
    "prime_test": task_prime_test,
    "factor_integer": task_factor_integer,
    "ec_summary": task_ec_summary,
    "finite_field_point_count": task_finite_field_point_count,
}


def main():
    raw = os.environ.get("BSD_TASK_JSON", "").strip()
    if not raw:
        raise ValueError("BSD_TASK_JSON is empty")

    task = json.loads(raw)
    if not isinstance(task, dict):
        raise ValueError("Task must be a JSON object")

    task_id = str(task.get("id", "unnamed"))
    kind = str(task.get("type", ""))
    params = task.get("params") or {}
    if kind not in HANDLERS:
        raise ValueError(f"Unsupported task type: {kind}")
    if not isinstance(params, dict):
        raise ValueError("params must be an object")

    started = datetime.now(timezone.utc)
    result_path = Path(os.environ.get("BSD_RESULT_PATH", "result.json"))
    result_path.parent.mkdir(parents=True, exist_ok=True)

    envelope = {
        "task_id": task_id,
        "task_type": kind,
        "worker_id": os.environ.get("BSD_WORKER_ID"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "started_at": started.isoformat(),
        "ok": False,
    }

    exit_code = 0
    try:
        envelope["result"] = _jsonable(HANDLERS[kind](params))
        envelope["ok"] = True
    except Exception as exc:
        envelope["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        exit_code = 1

    finished = datetime.now(timezone.utc)
    envelope["finished_at"] = finished.isoformat()
    envelope["duration_seconds"] = (finished - started).total_seconds()
    result_path.write_text(json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(envelope, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        result_path = Path(os.environ.get("BSD_RESULT_PATH", "result.json"))
        result_path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "ok": False,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        }
        result_path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        print(json.dumps(envelope, indent=2))
        sys.exit(1)

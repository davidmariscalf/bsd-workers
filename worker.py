#!/usr/bin/env python3
import io
import json
import os
import re
import subprocess
import sys
import tokenize
import traceback
from datetime import datetime, timezone
from pathlib import Path

from sage.all import EllipticCurve, GF, ZZ, factor, is_prime
from sage.env import SAGE_VERSION

MAX_SAGE_CODE_CHARS = 50000
MAX_SAGE_TIMEOUT_SECONDS = 21600
MAX_CAPTURE_CHARS = 2_000_000

_FORBIDDEN_PATTERNS = (
    (
        re.compile(r"(^|\n)\s*(import|from)\s+", re.IGNORECASE),
        "No imports are allowed in sage_code.",
    ),
    (
        re.compile(r"__", re.IGNORECASE),
        "Internal Python attributes are not allowed.",
    ),
    (
        re.compile(
            r"\b(open|exec|eval|compile|input|breakpoint|globals|locals|vars|"
            r"getattr|setattr|delattr)\s*\(",
            re.IGNORECASE,
        ),
        "The Sage code contains a forbidden system operation.",
    ),
    (
        re.compile(
            r"\b(os|sys|subprocess|socket|pathlib|shutil|requests|urllib|http|"
            r"ftplib|ctypes|pickle|marshal|multiprocessing|threading|asyncio)\b",
            re.IGNORECASE,
        ),
        "The Sage code attempts to access a forbidden system module.",
    ),
    (
        re.compile(r"\b(load|attach|save)\s*\(", re.IGNORECASE),
        "File read/write helpers are not allowed.",
    ),
    (
        re.compile(r"\b(system|popen|fork|spawn)\s*\(", re.IGNORECASE),
        "Process execution helpers are not allowed.",
    ),
)


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


def _contains_caret_operator(code):
    try:
        tokens = tokenize.generate_tokens(io.StringIO(code).readline)
        return any(
            token.type == tokenize.OP and token.string in {"^", "^="}
            for token in tokens
        )
    except (tokenize.TokenError, IndentationError):
        return "^" in code


def _validate_sage_code(code):
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Sage code cannot be empty.")
    if len(code) > MAX_SAGE_CODE_CHARS:
        raise ValueError(f"Sage code exceeds {MAX_SAGE_CODE_CHARS} characters.")
    if "\x00" in code:
        raise ValueError("Sage code contains a NUL character.")
    if re.search(
        r"(?m)^[ \t]*[A-Za-z_]\w*[ \t]*\.[ \t]*<[^>\n]+>[ \t]*=",
        code,
    ):
        raise ValueError(
            "SAGE_PREPARSER_SYNTAX_BLOCKED: use explicit Python Sage "
            "constructors instead of K.<z>=... or R.<x>=...."
        )
    if _contains_caret_operator(code):
        raise ValueError("Use ** for powers; ^ is blocked because it is XOR in sage -python.")
    for pattern, message in _FORBIDDEN_PATTERNS:
        if pattern.search(code):
            raise ValueError(message)
    return code.strip()


def _scrubbed_child_env():
    env = dict(os.environ)
    sensitive_fragments = (
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "PASSWD",
        "API_KEY",
        "PRIVATE_KEY",
        "CI_JOB_JWT",
        "ACTIONS_ID_TOKEN",
    )
    for key in list(env):
        upper = key.upper()
        if any(fragment in upper for fragment in sensitive_fragments):
            env.pop(key, None)
    return env


def _trim_output(text):
    text = text or ""
    if len(text) <= MAX_CAPTURE_CHARS:
        return text
    return text[:MAX_CAPTURE_CHARS] + "\n...[output truncated]"


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


def task_sage_code(params):
    code = _validate_sage_code(params["code"])
    timeout = int(params.get("timeout_seconds", 300))
    if timeout < 1 or timeout > MAX_SAGE_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout_seconds must be between 1 and {MAX_SAGE_TIMEOUT_SECONDS}"
        )

    script = (
        "from sage.all import *\n"
        "import warnings\n"
        "warnings.filterwarnings('ignore', category=DeprecationWarning)\n\n"
        + code
        + "\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=_scrubbed_child_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    stdout = _trim_output(completed.stdout)
    stderr = _trim_output(completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(
            "Sage code failed with exit code "
            f"{completed.returncode}.\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )
    return {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": int(completed.returncode),
        "timeout_seconds": timeout,
    }


HANDLERS = {
    "self_test": task_self_test,
    "prime_test": task_prime_test,
    "factor_integer": task_factor_integer,
    "ec_summary": task_ec_summary,
    "finite_field_point_count": task_finite_field_point_count,
    "sage_code": task_sage_code,
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
        "provider": os.environ.get("BSD_PROVIDER"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "gitlab_pipeline_id": os.environ.get("CI_PIPELINE_ID"),
        "gitlab_job_id": os.environ.get("CI_JOB_ID"),
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

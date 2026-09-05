#!/usr/bin/env python3
import argparse
import base64
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed


def _load_tasks(path):
    with open(path, "r", encoding="utf-8") as fh:
        tasks = json.load(fh)
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Task file must contain a non-empty JSON array")
    return tasks


def _run(host, task, user, key):
    payload = base64.b64encode(json.dumps(task, separators=(",", ":")).encode()).decode()
    cmd = [
        "ssh",
        "-i",
        key,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        "bsd-run-task",
        payload,
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    result = {
        "host": host,
        "task_id": str(task.get("id", "task")),
        "returncode": completed.returncode,
        "stderr": completed.stderr.strip(),
    }
    stdout = completed.stdout.strip()
    if stdout:
        try:
            result["result"] = json.loads(stdout)
        except json.JSONDecodeError:
            result["stdout"] = stdout
    return result


def main():
    parser = argparse.ArgumentParser(description="Dispatch BSD tasks over SSH to Oracle Always Free workers")
    parser.add_argument("tasks", help="JSON file containing a task array")
    args = parser.parse_args()

    hosts = [h.strip() for h in os.environ["BSD_ORACLE_HOSTS"].split(",") if h.strip()]
    key = os.environ["BSD_ORACLE_SSH_KEY"]
    user = os.environ.get("BSD_ORACLE_SSH_USER", "ubuntu")
    tasks = _load_tasks(args.tasks)

    if not hosts:
        raise ValueError("BSD_ORACLE_HOSTS is empty")

    results = []
    pending = list(tasks)
    while pending:
        batch = pending[: len(hosts)]
        del pending[: len(hosts)]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {
                pool.submit(_run, hosts[i], task, user, key): task
                for i, task in enumerate(batch)
            }
            for future in as_completed(futures):
                results.append(future.result())

    print(json.dumps(results, indent=2, sort_keys=True))
    if any(item["returncode"] != 0 for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

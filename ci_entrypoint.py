#!/usr/bin/env python3
import base64
import json
import os
import subprocess
import sys
from pathlib import Path


def _load_tasks():
    raw_b64 = os.environ.get("BSD_TASKS_B64", "").strip()
    raw_json = os.environ.get("BSD_TASKS_JSON", "").strip()
    if raw_b64:
        raw = base64.b64decode(raw_b64).decode("utf-8")
    elif raw_json:
        raw = raw_json
    else:
        raw = '[{"id":"self-test","type":"self_test","params":{}}]'

    tasks = json.loads(raw)
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("BSD tasks must be a non-empty JSON array")
    return tasks


def _index():
    if "CIRCLE_NODE_INDEX" in os.environ:
        return int(os.environ["CIRCLE_NODE_INDEX"]), "circleci"
    if "CI_NODE_INDEX" in os.environ:
        return int(os.environ["CI_NODE_INDEX"]) - 1, "gitlab"
    return 0, os.environ.get("BSD_PROVIDER", "generic")


def main():
    tasks = _load_tasks()
    index, provider = _index()
    if index < 0 or index >= len(tasks):
        print(f"No task for {provider} worker index {index}; exiting cleanly.")
        return 0

    task = dict(tasks[index])
    task.setdefault("id", f"task-{index + 1:02d}")
    task.setdefault("params", {})

    result_dir = Path(os.environ.get("BSD_RESULTS_DIR", "results"))
    result_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in "-_." else "-" for c in str(task["id"]))[:80]
    result_path = result_dir / f"{index + 1:02d}-{safe_id}.json"

    env = os.environ.copy()
    env["BSD_TASK_JSON"] = json.dumps(task, separators=(",", ":"))
    env["BSD_WORKER_ID"] = f"{provider}-{index + 1}"
    env["BSD_RESULT_PATH"] = str(result_path)
    env["BSD_PROVIDER"] = provider

    print(f"Running task {task['id']} on {provider} worker {index + 1}/{len(tasks)}")
    completed = subprocess.run([sys.executable, "worker.py"], env=env)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
import json
import os
import re

MAX_TASKS = 30
DEFAULT_TASKS = [{"id": "self-test", "type": "self_test", "params": {}}]


def _load_tasks():
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event == "repository_dispatch":
        raw = os.environ.get("DISPATCH_TASKS_JSON", "")
    elif event == "workflow_dispatch":
        raw = os.environ.get("MANUAL_TASKS_JSON", "")
    else:
        return DEFAULT_TASKS

    if not raw or raw == "null":
        return DEFAULT_TASKS
    tasks = json.loads(raw)
    if not isinstance(tasks, list):
        raise ValueError("tasks must be a JSON array")
    if not tasks:
        raise ValueError("tasks cannot be empty")
    if len(tasks) > MAX_TASKS:
        raise ValueError(f"At most {MAX_TASKS} tasks are allowed per workflow run")
    return tasks


def _slug(value):
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-.")
    return value[:48] or "task"


def main():
    tasks = _load_tasks()
    include = []
    for slot, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise ValueError(f"Task {slot} must be an object")
        if not task.get("type"):
            raise ValueError(f"Task {slot} is missing type")

        task = dict(task)
        task.setdefault("id", f"task-{slot:02d}")
        task.setdefault("params", {})
        if not isinstance(task["params"], dict):
            raise ValueError(f"Task {slot} params must be an object")

        include.append(
            {
                "slot": slot,
                "task_id": f"{slot:02d}-{_slug(task['id'])}",
                "task": task,
            }
        )

    matrix = {"include": include}
    output = f"matrix={json.dumps(matrix, separators=(',', ':'))}\n"
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()

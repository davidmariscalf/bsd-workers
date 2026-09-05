#!/usr/bin/env python3
import argparse
import base64
import json
import os
import urllib.parse
import urllib.request

MAX_TASKS = 30


def load_tasks(path):
    # utf-8-sig accepts ordinary UTF-8 and also strips the BOM written by
    # Windows PowerShell 5.x when Set-Content -Encoding UTF8 is used.
    with open(path, "r", encoding="utf-8-sig") as fh:
        tasks = json.load(fh)
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Task file must contain a non-empty JSON array")
    if len(tasks) > MAX_TASKS:
        raise ValueError(f"At most {MAX_TASKS} tasks per batch")
    return tasks


def request_json(url, *, method="POST", headers=None, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else {}


def dispatch_github(tasks):
    token = os.environ["BSD_GITHUB_TOKEN"]
    repo = os.environ.get("BSD_GITHUB_REPO", "davidmariscalf/bsd-workers")
    url = f"https://api.github.com/repos/{repo}/dispatches"
    status, body = request_json(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        payload={"event_type": "bsd_tasks", "client_payload": {"tasks": tasks}},
    )
    return {"provider": "github", "status": status, "response": body}


def dispatch_circleci(tasks):
    token = os.environ["BSD_CIRCLECI_TOKEN"]
    slug = os.environ["BSD_CIRCLECI_PROJECT_SLUG"]
    tasks_b64 = base64.b64encode(json.dumps(tasks, separators=(",", ":")).encode()).decode()
    url = f"https://circleci.com/api/v2/project/{slug}/pipeline"
    status, body = request_json(
        url,
        headers={"Circle-Token": token},
        payload={
            "branch": os.environ.get("BSD_CIRCLECI_BRANCH", "main"),
            "parameters": {"workers": len(tasks), "tasks_b64": tasks_b64},
        },
    )
    return {"provider": "circleci", "status": status, "response": body}


def dispatch_gitlab(tasks):
    token = os.environ["BSD_GITLAB_TOKEN"]
    project = os.environ["BSD_GITLAB_PROJECT"]
    ref = os.environ.get("BSD_GITLAB_REF", "main")
    project_q = urllib.parse.quote(project, safe="")
    tasks_b64 = base64.b64encode(json.dumps(tasks, separators=(",", ":")).encode()).decode()
    url = f"https://gitlab.com/api/v4/projects/{project_q}/pipeline?ref={urllib.parse.quote(ref)}"
    status, body = request_json(
        url,
        headers={"PRIVATE-TOKEN": token},
        payload={"inputs": {"workers": len(tasks), "tasks_b64": tasks_b64}},
    )
    return {"provider": "gitlab", "status": status, "response": body}


def main():
    parser = argparse.ArgumentParser(description="Dispatch BSD task batches to free CI providers")
    parser.add_argument("provider", choices=["github", "circleci", "gitlab"])
    parser.add_argument("tasks", help="Path to a JSON array of 1-30 tasks")
    args = parser.parse_args()

    tasks = load_tasks(args.tasks)
    dispatcher = {
        "github": dispatch_github,
        "circleci": dispatch_circleci,
        "gitlab": dispatch_gitlab,
    }[args.provider]
    print(json.dumps(dispatcher(tasks), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

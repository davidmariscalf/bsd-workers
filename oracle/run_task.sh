#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: bsd-run-task <base64-json-task>" >&2
  exit 2
fi

TASK_B64="$1"
TASK_JSON="$(printf '%s' "$TASK_B64" | base64 --decode)"
TASK_ID="$(python3 - "$TASK_JSON" <<'PY'
import json, re, sys
obj = json.loads(sys.argv[1])
raw = str(obj.get('id', 'task'))
print(re.sub(r'[^A-Za-z0-9_.-]+', '-', raw)[:80] or 'task')
PY
)"

cd /opt/bsd-workers
git pull --ff-only origin main >/dev/null 2>&1 || true
mkdir -p /opt/bsd-results

export BSD_TASK_JSON="$TASK_JSON"
export BSD_WORKER_ID="oracle-$(hostname)"
export BSD_PROVIDER="oracle"
export BSD_RESULT_PATH="/opt/bsd-results/${TASK_ID}.json"

/opt/sage/bin/sage -python worker.py
cat "$BSD_RESULT_PATH"

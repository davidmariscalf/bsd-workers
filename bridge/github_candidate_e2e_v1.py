#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import uuid
from pathlib import Path

ROOT = Path(r"C:\bsd-mcp")
BRIDGE = ROOT / "github_candidate_test_bridge_v1.py"
BRIDGE_SHA256 = "bdcbeccd37843ecbce0a419b66992be6dacd0e96fa8b2af0a8b2e4b15096a8c5"
VERSION = "BSD_GITHUB_CANDIDATE_E2E_V1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_bridge():
    if not BRIDGE.exists():
        raise RuntimeError("BRIDGE_NOT_FOUND")
    actual = sha256(BRIDGE)
    if actual != BRIDGE_SHA256:
        raise RuntimeError(f"BRIDGE_SHA256_MISMATCH {actual}")
    spec = importlib.util.spec_from_file_location("github_candidate_test_bridge_v1", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    b = load_bridge()
    pre = b.preflight()

    cid = "candidate_" + uuid.uuid4().hex[:16]
    token = uuid.uuid4().hex[:20]
    secret = uuid.uuid4().hex + uuid.uuid4().hex

    with tempfile.TemporaryDirectory(prefix="bsd-gh-e2e-") as td:
        root = Path(td)
        candidate = root / cid
        tests = candidate / "tests"
        tests.mkdir(parents=True)

        (candidate / "candidate_module.py").write_text(
            "def add(a, b):\n"
            "    return a + b\n",
            encoding="utf-8",
        )

        (tests / "test_smoke.py").write_text(
            "from candidate_module import add\n\n"
            "def test_add():\n"
            "    assert add(20, 22) == 42\n",
            encoding="utf-8",
        )

        fs = [
            candidate / "candidate_module.py",
            tests / "test_smoke.py",
        ]
        fp = b.fingerprint(candidate, fs)
        archive = root / "candidate.tar.gz"
        payload_sha = b.archive(candidate, fs, archive)

        srv = None
        th = None
        tun = None

        try:
            srv, th, served, port, route = b.serve(archive, secret)
            tun, base = b.tunnel(port)
            payload_url = base + route

            b.dispatch(cid, token, payload_url, payload_sha)
            rid = b.runid(cid, token)
            meta = b.wait(rid)

            result_path = b.resultfile(
                rid,
                token,
                root / "artifact",
            )

            raw = json.loads(
                result_path.read_text(encoding="utf-8")
            )

            result = b.validate(
                raw,
                cid,
                token,
                rid,
                fp,
            )

            if result.get("classification") != "PASS":
                raise RuntimeError(
                    "E2E_NOT_PASS "
                    + json.dumps(result, sort_keys=True)
                )

            if not served.is_set():
                raise RuntimeError("PAYLOAD_WAS_NOT_FETCHED")

            if meta.get("status") != "completed":
                raise RuntimeError("GITHUB_RUN_NOT_COMPLETED")

            out = {
                "version": VERSION,
                "e2e": "PASS",
                "candidate_id": cid,
                "synthetic_candidate": True,
                "github_run_id": rid,
                "github_url": meta.get("url"),
                "github_conclusion": meta.get("conclusion"),
                "classification": result.get("classification"),
                "tests_passed": result.get("tests_passed"),
                "passed": result.get("passed"),
                "failed": result.get("failed"),
                "errors": result.get("errors"),
                "provider": result.get("provider"),
                "backend": result.get("backend"),
                "image_ref": result.get("image_ref"),
                "network_disabled": result.get("network_disabled"),
                "rootfs_readonly": result.get("rootfs_readonly"),
                "candidate_mount_readonly": result.get("candidate_mount_readonly"),
                "non_root": result.get("non_root"),
                "production_active": False,
                "automatically_promoted": False,
                "mathematical_certification": False,
                "database_modified": False,
                "promotion_gate_modified": False,
                "f776_touched": False,
                "preflight": pre,
            }
            print(json.dumps(out, indent=2, sort_keys=True))
            return 0
        finally:
            b.stop(tun)
            if srv is not None:
                srv.shutdown()
                srv.server_close()
            if th is not None:
                th.join(5)


if __name__ == "__main__":
    raise SystemExit(main())

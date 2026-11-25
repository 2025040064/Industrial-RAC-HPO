#!/usr/bin/env python3
"""Upload the rebuilt image, create a submission, and run one controlled trial.

Credentials are read locally at runtime and never printed or written to disk.
All API responses and state IDs are saved under this experiment directory.
"""
import argparse
import base64
import json
import os
import sqlite3
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
BASE = "https://rsi-index.115.zone/api/v1"
STATE_PATH = ROOT / "platform-state.json"


def safari_token():
    p = Path.home() / ("Library/Containers/com.apple.Safari/Data/Library/WebKit/WebsiteData/"
                       "Default/68L7HZdu-l-zIxdTX2wJLrxxsVzpCBdVVOoNMSWtBUE/"
                       "68L7HZdu-l-zIxdTX2wJLrxxsVzpCBdVVOoNMSWtBUE/LocalStorage/localstorage.sqlite3")
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    value = con.execute("SELECT value FROM ItemTable WHERE key='contest_session'").fetchone()[0]
    return json.loads(value.decode("utf-16-le").lstrip("\ufeff"))["token"]


def pytrio_api_key():
    cfg = tomllib.load((Path.home() / ".pytrio/config.toml").open("rb"))
    key = cfg.get("api_key")
    if not isinstance(key, str) or len(key) < 8:
        raise RuntimeError("PyTRIO api_key missing in ~/.pytrio/config.toml")
    return key


TOKEN = safari_token()
_state_cache = {}


def call(method, path, payload=None, raw=None, content_type=None, timeout=300):
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
    data = None
    if raw is not None:
        data = raw
        headers["Content-Type"] = content_type
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} {path}: {body[:500]}")
    return json.loads(body) if body else {}


def save(name, data):
    p = ROOT / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def wait_archive(archive_id, max_checks=60, interval=5):
    for i in range(max_checks):
        data = call("GET", "/image-archives")
        items = [x for x in data.get("items", []) if x["id"] == archive_id]
        if not items:
            raise RuntimeError(f"archive {archive_id} not listed")
        item = items[0]
        print(f"[archive] check {i+1}: status={item.get('status')} "
              f"cleanup={item.get('cleanup_status')} local_bytes={item.get('local_bytes')}", flush=True)
        if item.get("status") == "ready" and item.get("cleanup_status") in (None, "clean", "cleaned"):
            return item
        if item.get("status") in ("failed", "expired") or item.get("error_code"):
            raise RuntimeError(f"archive failed: {json.dumps(item, ensure_ascii=False)}")
        time.sleep(interval)
    raise TimeoutError("archive did not become ready in time")


def validate_submission(submission_id, max_checks=40, interval=5):
    if not _state_cache.get("validated"):
        resp = call("POST", f"/submissions/{submission_id}/validate")
        save("validate-response.json", resp)
        _state_cache["validated"] = True
        save_state(_state_cache)
        print(f"[validate] requested: {json.dumps(resp, ensure_ascii=False)[:300]}", flush=True)
    for i in range(max_checks):
        data = call("GET", "/submissions")
        items = [x for x in data.get("items", []) if x["id"] == submission_id]
        if not items:
            raise RuntimeError(f"submission {submission_id} not listed")
        item = items[0]
        print(f"[validate] check {i+1}: status={item.get('status')} "
              f"error={item.get('validation_error') or '-'}", flush=True)
        if item.get("status") in ("valid", "frozen"):
            return item
        if item.get("status") == "invalid":
            raise RuntimeError(f"submission validation failed: {item.get('validation_error')}")
        time.sleep(interval)
    raise TimeoutError("submission did not validate in time")


def wait_run(submission_id, max_checks=480, interval=15):
    last_id = None
    for i in range(max_checks):
        data = call("GET", "/runs")
        runs = [x for x in data.get("items", [])
                if x.get("submission_id") == submission_id and x.get("mode") == "trial"]
        if not runs:
            print(f"[run] check {i+1}: no trial yet", flush=True)
            time.sleep(interval)
            continue
        run = sorted(runs, key=lambda x: x.get("created_at", ""))[-1]
        if run["id"] != last_id:
            print(f"[run] {run['id']} status={run.get('status')} "
                  f"failure={run.get('failure_reason') or '-'}", flush=True)
            last_id = run["id"]
        if run.get("status") in ("completed", "failed", "rejected", "cancelled"):
            return run
        time.sleep(interval)
    raise TimeoutError("trial run did not finish in time")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-trial", action="store_true")
    args = ap.parse_args()

    global _state_cache
    _state_cache = load_state()
    state = _state_cache
    receipt = json.loads((REPO / "workspace/contest_sampler/selection-contract-20261124/submission.json").read_text())
    rules = json.loads((REPO / "experiments/platform-runs/platform-rules.json").read_text())
    config_id = rules["rules"]["evaluation_config_id"]

    if not state.get("archive_id"):
        tar = ROOT / "harness-selection-contract.tar"
        print(f"[upload] {tar.stat().st_size} bytes", flush=True)
        resp = call("POST", "/image-archives", raw=tar.read_bytes(), content_type="application/x-tar")
        save("upload-response.json", resp)
        state["archive_id"] = resp["id"]
        save_state(state)
        print(f"[upload] archive_id={resp['id']}", flush=True)
    archive = wait_archive(state["archive_id"])

    if not state.get("document_id"):
        note = ROOT / "submission-note.md"
        payload = {"name": note.name,
                   "content_base64": base64.b64encode(note.read_bytes()).decode("ascii")}
        resp = call("POST", "/documents", payload=payload)
        save("document-response.json", resp)
        state["document_id"] = resp["id"]
        save_state(state)
        print(f"[document] document_id={resp['id']}", flush=True)

    if not state.get("submission_id"):
        payload = {
            "model": receipt["sampler_path"],
            "model_source": "sampler",
            "base_model_confirmed": False,
            "api_key": pytrio_api_key(),
            "training_url": receipt["training_record_url"],
            "source_url": "https://github.com/2025040064/Industrial-RAC-HPO.git",
            "image_archive_id": archive["id"],
            "document_id": state["document_id"],
        }
        resp = call("POST", "/submissions", payload=payload)
        save("submission-response.json", resp)
        state["submission_id"] = resp["id"]
        save_state(state)
        print(f"[submission] submission_id={resp['id']} version={resp.get('version')}", flush=True)

    if args.skip_trial:
        print("[done] --skip-trial; upload/submission only", flush=True)
        return

    validate_submission(state["submission_id"])

    if not state.get("trial_run_id"):
        payload = {"evaluation_config_id": config_id, "execution": "full_training"}
        resp = call("POST", f"/submissions/{state['submission_id']}/trial", payload=payload)
        save("trial-response.json", resp)
        state["trial_run_id"] = resp.get("id")
        save_state(state)
        print(f"[trial] run_id={resp.get('id')} status={resp.get('status')}", flush=True)

    run = wait_run(state["submission_id"])
    state["run"] = run
    save_state(state)
    report = call("GET", f"/runs/{run['id']}/report", timeout=120)
    out = REPO / "experiments/platform-runs" / f"{run['id']}-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[report] saved {out}", flush=True)

    wr = report.get("report", {}).get("workspace_report") or {}
    from collections import Counter
    actions = Counter(rd.get("configuration", {}).get("model_action")
                      for ds in wr.get("datasets", []) for rd in ds.get("rounds", []))
    costs = report.get("report", {}).get("costs", {})
    print(f"[summary] run={run['id']} status={run.get('status')} actions={dict(actions)} "
          f"completion_tokens={costs.get('completion_tokens')}", flush=True)


if __name__ == "__main__":
    main()

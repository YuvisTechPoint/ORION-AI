import sys
import httpx

API_BASE = "http://localhost:8000"

if len(sys.argv) < 2:
    print("usage: python scripts/inspect_pipeline_stages.py <pipeline_id>")
    sys.exit(1)

pipeline_id = sys.argv[1]

with httpx.Client(base_url=API_BASE, timeout=30.0) as client:
    resp = client.get(f"/pipeline-status/{pipeline_id}")
    resp.raise_for_status()
    data = resp.json()

history = data.get("history", [])
artifacts = data.get("artifacts", {})
stages = [item.get("stage") for item in history if isinstance(item, dict) and item.get("stage")]

print("pipeline_id:", pipeline_id)
print("current_stage:", data.get("current_stage"))
print("status:", data.get("status"))
print("unique_history_stages:", sorted(set(stages)))
print("history_count:", len(history))
print("artifact_keys:", sorted(artifacts.keys()))
summary = artifacts.get("pipeline_summary", {}) if isinstance(artifacts, dict) else {}
print("pipeline_summary:", summary)

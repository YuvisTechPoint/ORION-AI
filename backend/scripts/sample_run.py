import json

import httpx


def main() -> None:
    with open("../samples/submit_code_request.json", "r", encoding="utf-8") as f:
        payload = json.load(f)

    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30.0) as client:
        submit = client.post("/submit-code", json=payload)
        submit.raise_for_status()
        submit_data = submit.json()
        print("Submit response:", json.dumps(submit_data, indent=2))

        pipeline_id = submit_data["pipeline_id"]
        status = client.get(f"/pipeline-status/{pipeline_id}")
        status.raise_for_status()
        print("Pipeline status:", json.dumps(status.json(), indent=2))

        with open("../samples/logs.txt", "r", encoding="utf-8") as f:
            logs = f.read()
        monitor = client.post("/analyze-logs", json={"pipeline_id": pipeline_id, "logs": logs})
        monitor.raise_for_status()
        print("Monitoring:", json.dumps(monitor.json(), indent=2))


if __name__ == "__main__":
    main()

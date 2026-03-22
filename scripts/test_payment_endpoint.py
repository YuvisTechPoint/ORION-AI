import httpx

API_BASE = "http://localhost:8000"

with httpx.Client(base_url=API_BASE, timeout=30.0) as client:
    try:
        files = {"files": ("test.txt", "dummy text content", "text/plain")}
        data = {"text_input": "hello from smoke test"}
        resp = client.post("/api/v1/multimodal/payment", files=files, data=data)
        print("status:", resp.status_code)
        print("headers:", resp.headers)
        print("text:\n", resp.text)
    except Exception as e:
        print("error:", e)

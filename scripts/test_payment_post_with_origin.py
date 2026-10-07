import httpx
API_BASE = "http://localhost:8000"
with httpx.Client(base_url=API_BASE, timeout=30.0) as client:
    files = {"files": ("test.txt", "dummy text content", "text/plain")}
    data = {"text_input": "hello from smoke test"}
    headers={'Origin':'http://localhost:5173'}
    resp = client.post("/api/v1/multimodal/payment", files=files, data=data, headers=headers)
    print('status:', resp.status_code)
    print('headers:')
    for k,v in resp.headers.items():
        if k.lower().startswith('access-control-'):
            print(k+':', v)
    print('all headers:', dict(resp.headers))
    print('text:', resp.text)

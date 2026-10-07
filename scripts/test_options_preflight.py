import httpx

API='http://localhost:8000'
path='/api/v1/multimodal/payment'
headers={
 'Origin':'http://localhost:5173',
 'Access-Control-Request-Method':'POST',
 'Access-Control-Request-Headers':'content-type',
}
with httpx.Client(base_url=API, timeout=10.0) as c:
    r=c.options(path, headers=headers)
    print('status', r.status_code)
    for k,v in r.headers.items():
        if k.lower().startswith('access-control-'):
            print(k+':', v)
    print('all headers:', dict(r.headers))

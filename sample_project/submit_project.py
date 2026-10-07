import zipfile
import json
import requests
from pathlib import Path

zip_path = Path('sample_project.zip')
with zipfile.ZipFile(zip_path, 'r') as z:
    repo_files = {}
    for info in z.infolist():
        if info.is_dir():
            continue
        name = info.filename
        # read text files as utf-8
        try:
            data = z.read(name).decode('utf-8')
        except Exception:
            data = ''
        repo_files[name] = data

payload = {
    'repo_name': 'sample_project',
    'code': 'example',
    'repo_files': repo_files,
    'force_real': True
}

resp = requests.post('http://127.0.0.1:8000/submit-code', json=payload, timeout=30)
print(resp.status_code)
print(resp.text)

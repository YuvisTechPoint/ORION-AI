import zipfile
import json
from pathlib import Path

zip_path = Path('sample_project.zip')
with zipfile.ZipFile(zip_path, 'r') as z:
    repo_files = {}
    for info in z.infolist():
        if info.is_dir():
            continue
        name = info.filename
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

with open('payload.json', 'w', encoding='utf-8') as f:
    json.dump(payload, f)

print('payload.json written')

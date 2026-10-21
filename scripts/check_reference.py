"""Read-only verification of all reference files recorded before deriving this app."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
reports = []
for directory, manifest in [('vedio', 'reference-hashes.json'), ('webTi/Answering', 'webti-reference-hashes.json')]:
    source = root.parent/directory
    expected = json.loads((root/manifest).read_text(encoding='utf-8'))
    changed = [name for name, digest in expected.items() if not (source/name).is_file()
               or hashlib.sha256((source/name).read_bytes()).hexdigest() != digest]
    reports.append({'project': directory, 'checked': len(expected), 'changed': changed, 'ok': not changed})
ok = all(report['ok'] for report in reports)
print(json.dumps({'ok': ok, 'projects': reports}, ensure_ascii=False))
raise SystemExit(not ok)

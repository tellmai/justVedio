"""Create a complete offline portable ZIP with its integrity checksum."""
import hashlib
import json
import zipfile
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
sys.path.insert(0,str(ROOT))
from justvedio.version import APP_NAME, VERSION

def checksum(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'file':path.name, 'bytes':path.stat().st_size, 'sha256':digest}

def main(source_only=False):
    destination = DIST / f'{APP_NAME}-Portable-{VERSION}-x64.zip'
    if not source_only:
        app = DIST / f'v{VERSION}' / APP_NAME
        if not (app/f'{APP_NAME}.exe').is_file():
            raise RuntimeError('请先构建 EXE')
        files = sorted(p for p in app.rglob('*') if p.is_file() and 'results' not in p.relative_to(app).parts)
        print('Creating portable ZIP:', len(files), 'files', flush=True)
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for path in files:
                archive.write(path,path.relative_to(app.parent))
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip():
            raise RuntimeError('ZIP 完整性验证失败')
    results = [checksum(destination)]
    source_zip = DIST / f'{APP_NAME}-Source-{VERSION}.zip'
    excluded = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist', 'results', 'tools'}
    with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob('*')):
            relative = path.relative_to(ROOT)
            if path.is_file() and not excluded.intersection(relative.parts):
                archive.write(path, str(Path(f'{APP_NAME}-Source') / relative))
    with zipfile.ZipFile(source_zip) as archive:
        if archive.testzip():
            raise RuntimeError('源码 ZIP 完整性验证失败')
    results.append(checksum(source_zip))
    (DIST/'release-manifest.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    (DIST/'SHA256SUMS.txt').write_text(''.join(f"{r['sha256']}  {r['file']}\n" for r in results),encoding='ascii')
    print(json.dumps(results,ensure_ascii=False),flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-only', action='store_true', help='仅更新源码包和摘要，保留已验证的成品 ZIP')
    main(parser.parse_args().source_only)

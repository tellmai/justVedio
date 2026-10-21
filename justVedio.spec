# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from importlib.metadata import distributions
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH)
datas = collect_data_files('ddddocr') + collect_data_files('playwright')
datas += [(str(root/'README.md'), '.'), (str(root/'THIRD_PARTY_NOTICES.md'), '.')]
datas += [(str(root/'justvedio/assets'), 'justvedio/assets')]
for distribution in distributions():
    for item in distribution.files or []:
        parts=tuple(str(p).lower() for p in item.parts)
        if any(p.endswith('.dist-info') for p in parts) and any('license' in p or p in ('copying','notice','authors') for p in parts):
            file=Path(distribution.locate_file(item))
            if file.is_file():
                datas.append((str(file),'licenses/'+distribution.metadata['Name']))
chrome=root/'tools/chrome'
if chrome.exists():
    datas.append((str(chrome),'chrome'))
a=Analysis([str(root/'main.py')],pathex=[str(root)],binaries=collect_dynamic_libs('onnxruntime'),datas=datas,
    hiddenimports=['ddddocr','onnxruntime','PIL','openpyxl','playwright.async_api'],
    excludes=['tkinter','matplotlib','IPython','notebook','pytest','pandas','scipy','pdfplumber','pdfminer','pypdfium2','reportlab'],noarchive=False)
a.binaries=[entry for entry in a.binaries if Path(entry[0]).name.lower() not in {'icuuc.dll','icuin.dll','icudt78.dll'}]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='justVedio',debug=False,strip=False,upx=False,console=False,
    icon=str(root/'justvedio/assets/app.ico'),version=str(root/'scripts/windows-version.txt'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='justVedio')

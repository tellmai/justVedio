"""Verify the actual final ZIP on Windows without a configured Python environment."""
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from justvedio.version import APP_NAME, VERSION


def main():
    archive = ROOT/f'dist/{APP_NAME}-Portable-{VERSION}-x64.zip'
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    extract = ROOT/f'build/便携包 {VERSION} 解压验收 {stamp}'
    output = ROOT/f'build/portable-smoke-{stamp}'
    extract.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        required = [f'{APP_NAME}/{APP_NAME}.exe', f'{APP_NAME}/使用说明.txt',
                    f'{APP_NAME}/_internal/chrome/chrome-win64/chrome.exe']
        if not all(name in z.namelist() for name in required) or z.testzip():
            raise RuntimeError('ZIP 缺少必需文件或完整性校验失败')
        for name in z.namelist():
            if not (extract/name).resolve().is_relative_to(extract.resolve()):
                raise RuntimeError('ZIP 存在异常路径')
            if any(term in name.lower() for term in ('mock_exam', 'selftest-bank', 'pdfplumber', 'pdfminer', 'pypdfium2')):
                raise RuntimeError('便携包仍含专用答题依赖或资源：'+name)
        z.extractall(extract)
    env = dict(os.environ)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
        env.pop(key, None)
    system_root = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    env['PATH'] = os.pathsep.join((str(system_root/'System32'), str(system_root)))
    env['QT_QPA_PLATFORM'] = 'windows'
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    result = subprocess.run([str(extract/APP_NAME/f'{APP_NAME}.exe'), '--smoke-test', str(output), '--desktop-selftest'],
                            cwd=extract, env=env, timeout=180, startupinfo=startup,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    report = json.loads((output/'gui-smoke.json').read_text(encoding='utf-8'))
    expected = ('ok', 'frozen', 'brand_matches', 'login_only_available', 'test_without_bank', 'background_checkbox', 'no_tray',
                'no_answering_ui', 'expiry_enforced', 'identity_import', 'statistics_export', 'ocr_model',
                'browser_launch', 'bundled_browser', 'video_playback', 'twelve_full_flows', 'identity_isolation',
                'direct_video_transition', 'desktop_background', 'headless_browser', 'background_execution',
                'main_window_visible', 'foreground_mode', 'execution_controls_locked', 'power_request_released',
                'no_answering_fields', 'background_preserved_foreground')
    if result.returncode or not all(report.get(key) for key in expected):
        raise RuntimeError('最终 EXE 自检失败：'+json.dumps(report, ensure_ascii=False))
    if report['app_name'] != APP_NAME or report['version'] != VERSION:
        raise RuntimeError('最终 EXE 名称或版本不一致')
    report.update(portable_archive=archive.name, unicode_and_space_path=True, python_environment_removed=True,
                  exit_code=result.returncode, extract_path=str(extract), output_path=str(output))
    (ROOT/f'build/portable-verification-{VERSION}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

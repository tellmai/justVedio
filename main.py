import argparse
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='justVedio：身份登录与视频观看助手')
    parser.add_argument('--smoke-test', metavar='OUTPUT_DIR', help='离线自检，不提交真实身份')
    parser.add_argument('--desktop-selftest', action='store_true', help='验收主界面保留、浏览器后台播放及前台模式')
    args = parser.parse_args()
    if args.smoke_test and not args.desktop_selftest:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont, QFontDatabase, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from justvedio.expiry import is_expired, EXPIRY_MESSAGE
    from justvedio.version import APP_NAME, ORGANIZATION, VERSION
    from justvedio.privacy import redact
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION)
    app.setQuitOnLastWindowClosed(True)
    resources = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    app.setWindowIcon(QIcon(str(resources / 'justvedio/assets/app.ico')))
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    family = 'Microsoft YaHei UI'
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            family = families[0]
    app.setFont(QFont(family, 10))
    if is_expired():
        if args.smoke_test:
            output = Path(args.smoke_test).resolve()
            output.mkdir(parents=True, exist_ok=True)
            (output/'gui-smoke.json').write_text(json.dumps({'ok': False, 'expired': True, 'message': EXPIRY_MESSAGE}, ensure_ascii=False), encoding='utf-8')
        else:
            QMessageBox.critical(None, '软件已过期', EXPIRY_MESSAGE)
        return 1
    from justvedio.gui import MainWindow
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    log_dir = base / 'results/logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    class PrivateFormatter(logging.Formatter):
        def format(self, record):
            return redact(super().format(record))
    handler = RotatingFileHandler(log_dir/f'{APP_NAME}.log', maxBytes=1000000, backupCount=2, encoding='utf-8')
    handler.setFormatter(PrivateFormatter('%(asctime)s %(message)s'))
    logger = logging.getLogger('justvedio')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    window = MainWindow()
    window.show()
    result = {}
    if args.smoke_test:
        output = Path(args.smoke_test).resolve()
        output.mkdir(parents=True, exist_ok=True)
        def smoke():
            if not window.backend_ready and window.backend.isRunning():
                QTimer.singleShot(100, smoke)
                return
            try:
                from justvedio.selftest import check_gui, run_runtime_checks
                result.update(check_gui(window, app, output))
                result.update(run_runtime_checks(output, desktop=args.desktop_selftest, window=window))
                result.update(ok=window.backend_ready, app_name=APP_NAME, version=VERSION,
                              frozen=bool(getattr(sys, 'frozen', False)))
            except Exception as error:
                result.update(ok=False, error=type(error).__name__, detail=str(error).split('Call log:')[0])
            finally:
                (output/'gui-smoke.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                window.close()
        QTimer.singleShot(300, smoke)
    code = app.exec()
    logger.removeHandler(handler)
    handler.close()
    return (0 if result.get('ok') else 1) if args.smoke_test else code


if __name__ == '__main__':
    raise SystemExit(main())

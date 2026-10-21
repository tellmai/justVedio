import os
import sys
import pytest
from PySide6.QtWidgets import QApplication
from justvedio.gui import MainWindow
from justvedio.selftest import check_gui, run_runtime_checks
from test_integration import wait


@pytest.mark.skipif(sys.platform != 'win32' or os.environ.get('RUN_DESKTOP_TEST') != '1',
                    reason='需要显式启用真实 Windows 桌面')
def test_browser_hidden_while_main_interface_remains_available(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        wait(app, lambda: window.backend_ready)
        assert all(check_gui(window, app, tmp_path).values())
        result = run_runtime_checks(tmp_path, desktop=True, window=window)
        assert result['desktop_background'] and result['main_window_visible']
        assert result['headless_browser'] and result['foreground_mode'] and result['execution_controls_locked']
        assert result['completed'] == 12 and result['power_request_released']
    finally:
        window.close()
        wait(app, lambda: not window.backend.isRunning())
        window._finish_close()

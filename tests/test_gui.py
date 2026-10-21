from dataclasses import replace
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from justvedio.gui import MainWindow
from justvedio.models import Candidate, IdentityImport, DEFAULT_VIDEO_URL
from justvedio.batch import PersonResult
from test_integration import wait


def test_ui_modes_dispatch_retry_and_video_only_columns(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = []
    try:
        wait(app, lambda: window.backend_ready)
        window.settings = QSettings(str(tmp_path/'settings.ini'), QSettings.IniFormat)
        window.background.setChecked(True)
        monkeypatch.setattr(window.backend, 'start_job', lambda *args, **kwargs: calls.append((args, kwargs)))
        person = Candidate(2, '黔江区', '合成人员', '110101199001010010')
        window.identities_loaded(IdentityImport([person], [], '测试'))
        assert not window.test_mode.isChecked() and window.start_button.text() == '启动登录验证'
        assert not hasattr(window, 'questions') and not hasattr(window, 'bank_button')
        window.video_url.setText('invalid video ignored for login only')
        window._start('watch')
        assert len(calls) == 1 and calls[0][1] == {'test_mode': False}
        assert calls[0][0][5].background is True
        assert window.settings.value('background', type=bool) is True
        assert not window.background.isEnabled() and not window.concurrency.isEnabled()
        window._finished()
        assert window.background.isEnabled() and window.concurrency.isEnabled()
        window.background.setChecked(False)
        window.test_mode.setChecked(True)
        assert window.start_button.text() == '启动测试' and window.start_button.isEnabled()
        window._start('watch')
        assert len(calls) == 1
        window.video_url.setText(DEFAULT_VIDEO_URL)
        window._start('watch')
        assert len(calls) == 2 and calls[1][1] == {'test_mode': True}
        assert calls[1][0][5].background is False
        assert window.settings.value('background', type=bool) is False
        record = PersonResult(0, person, status='watching')
        window._batch_started(str(tmp_path), [record])
        window._person_updated(replace(record, progress=45, videos_completed=2, reason='正常播放'))
        table = window.tables['active']
        assert table.columnCount() == 8
        assert [table.item(0, i).text() for i in (5, 6, 7)] == ['45.0%', '2', '正常播放']
        window._person_updated(replace(record, status='completed', progress=100, videos_completed=1))
        window._finished()
        assert not window._remaining() and not window.start_button.isEnabled()
        window.test_mode.setChecked(False)
        assert window._remaining() == [person] and window.start_button.isEnabled()
        assert not window.settings.contains('exam_score_min')
    finally:
        window.close()
        wait(app, lambda: not window.backend.isRunning())
        window._finish_close()


def test_background_preference_restored_and_interface_stays_visible(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path/'settings.ini'), QSettings.IniFormat)
    monkeypatch.setattr('justvedio.gui.application_settings', lambda: settings)
    window = MainWindow()
    try:
        wait(app, lambda: window.backend_ready)
        window.show()
        assert window.background.isChecked() and window.background.text() == '后台执行（隐藏浏览器）'
        assert not hasattr(window, 'tray') and not hasattr(window, 'background_button')
        window.background.setChecked(False)
        window.busy = True
        window._controls()
        assert window.isVisible() and not window.background.isEnabled()
        assert window.pause_button.isEnabled() and window.stop_button.isEnabled()
        window._finished()
        assert window.isVisible() and window.background.isEnabled()
        settings.setValue('background', False)
    finally:
        window.close()
        wait(app, lambda: not window.backend.isRunning())
        window._finish_close()
    restored = MainWindow()
    try:
        wait(app, lambda: restored.backend_ready)
        assert not restored.background.isChecked()
    finally:
        restored.close()
        wait(app, lambda: not restored.backend.isRunning())
        restored._finish_close()


def test_settings_are_independent():
    from justvedio.settings import application_settings
    settings = application_settings()
    assert settings.organizationName() == 'LocalTools' and settings.applicationName() == 'justVedio'

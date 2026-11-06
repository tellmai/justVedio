from dataclasses import replace
from datetime import datetime
from openpyxl import Workbook
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from justvedio.gui import MainWindow
from justvedio.models import Candidate, IdentityImport
from justvedio.batch import PersonResult
from test_integration import wait


def test_ui_dispatch_retry_and_browser_columns(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path/'settings.ini'), QSettings.IniFormat)
    monkeypatch.setattr('justvedio.gui.application_settings', lambda: settings)
    window = MainWindow()
    calls = []
    try:
        wait(app, lambda: window.backend_ready)
        assert window._selected_browsers()
        window.background.setChecked(True)
        monkeypatch.setattr(window.backend, 'start_job', lambda *args, **kwargs: calls.append((args, kwargs)))
        person = Candidate(2, '黔江区', '合成人员', '110101199001010010')
        window.identities_loaded(IdentityImport([person], [], '测试'))
        assert window.start_button.text() == '启动视频学习'
        assert not hasattr(window, 'test_mode')
        assert not hasattr(window, 'questions') and not hasattr(window, 'bank_button')
        window._start('watch')
        assert len(calls) == 1
        assert [choice.path for choice in calls[0][1]['browsers']] == [choice.path for choice in window._selected_browsers()]
        assert isinstance(calls[0][1]['started_at'], datetime)
        assert calls[0][0][5].background is True
        saved = settings.value('browsers')
        saved = [saved] if isinstance(saved, str) else list(saved)
        assert saved == [choice.path for choice in window._selected_browsers()]
        assert settings.value('background', type=bool) is True
        assert not window.background.isEnabled() and all(not box.isEnabled() for box in window.browser_boxes.values())
        window._finished()
        assert window.background.isEnabled() and all(box.isEnabled() for box in window.browser_boxes.values())
        window.background.setChecked(False)
        window._start('watch')
        assert len(calls) == 2 and calls[1][0][5].background is False
        assert settings.value('learning_entry') == '开始旁听学习|继续旁听学习'
        assert settings.value('background', type=bool) is False
        record = PersonResult(0, person, status='watching', browser='测试浏览器1')
        window._batch_started(str(tmp_path), [record])
        window._person_updated(replace(record, progress=45, videos_completed=0, reason='正在播放'))
        table = window.tables['active']
        assert table.columnCount() == 9
        assert [table.item(0, i).text() for i in (4, 6, 7, 8)] == ['测试浏览器1', '45.0%', '0', '正在播放']
        window._person_updated(replace(record, status='completed', progress=100))
        window._finished()
        assert not window._remaining() and not window.start_button.isEnabled()
        assert not settings.contains('exam_score_min')
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
        assert window._selected_browsers()
        assert not hasattr(window, 'tray') and not hasattr(window, 'background_button')
        window.background.setChecked(False)
        window.busy = True
        window._controls()
        assert window.isVisible() and not window.background.isEnabled()
        assert all(not box.isEnabled() for box in window.browser_boxes.values())
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
        assert restored._selected_browsers()
    finally:
        restored.close()
        wait(app, lambda: not restored.backend.isRunning())
        restored._finish_close()


def test_start_requires_a_selected_browser(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path/'settings.ini'), QSettings.IniFormat)
    monkeypatch.setattr('justvedio.gui.application_settings', lambda: settings)
    window = MainWindow()
    try:
        wait(app, lambda: window.backend_ready)
        window.identities_loaded(IdentityImport([Candidate(2, '黔江区', '合成人员', '110101199001010010')], [], '测试'))
        assert window.browser_boxes
        for box in window.browser_boxes.values():
            box.setChecked(False)
        assert not window.start_button.isEnabled()
        window._start('watch')
        assert '至少勾选一个浏览器' in window.status.text()
        window.browser_select_all.click()
        assert window.start_button.isEnabled()
        assert all(box.isChecked() for box in window.browser_boxes.values())
        window.browser_select_all.click()
        assert not any(box.isChecked() for box in window.browser_boxes.values())
        assert not window.start_button.isEnabled()
    finally:
        window.close()
        wait(app, lambda: not window.backend.isRunning())
        window._finish_close()


def test_auto_loads_identity_folder(tmp_path, monkeypatch, isolated_application_base):
    folder = isolated_application_base/'人员信息'
    folder.mkdir(parents=True)
    for index, name in enumerate(('自动甲', '自动乙')):
        book = Workbook()
        sheet = book.active
        sheet.append(['所在的区县', '姓名', '身份证号'])
        sheet.append(['黔江区', name, f'11010119900101{index+1:04}'])
        book.save(folder/f'身份{index+1}.xlsx')
        book.close()
    (folder/'忽略.txt').write_text('not an identity file', encoding='utf-8')
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path/'settings.ini'), QSettings.IniFormat)
    monkeypatch.setattr('justvedio.gui.application_settings', lambda: settings)
    window = MainWindow()
    try:
        wait(app, lambda: window.candidates, 15)
        assert {c.name for c in window.candidates} == {'自动甲', '自动乙'}
        assert '2 个文件' in window.identity_summary.text()
        assert window.start_button.text() == '启动视频学习'
    finally:
        window.close()
        wait(app, lambda: not window.backend.isRunning())
        window._finish_close()


def test_settings_are_independent():
    from justvedio.settings import application_settings
    settings = application_settings()
    assert settings.organizationName() == 'LocalTools' and settings.applicationName() == 'justVedio'

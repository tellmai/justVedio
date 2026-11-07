from datetime import datetime
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from justvedio import expiry
from justvedio.gui import MainWindow
from test_integration import wait


@pytest.mark.parametrize('instant,expected',[
    ('2027-05-20T23:59:59.999999+08:00',False),
    ('2027-05-21T00:00:00+08:00',True),
    ('2027-05-20T15:59:59.999999+00:00',False),
    ('2027-05-20T16:00:00+00:00',True),
    ('2027-05-21T01:00:00+09:00',True),
    ('2027-05-20T23:59:59',False),
])
def test_inclusive_end_date_and_pc_timezone(instant,expected):
    assert expiry.is_expired(datetime.fromisoformat(instant)) is expected


def test_expired_entry_exits_silently_without_any_message(monkeypatch, capsys):
    import main
    notices=[]
    monkeypatch.setattr('sys.argv',['justVedio'])
    monkeypatch.setattr(expiry,'is_expired',lambda:True)
    monkeypatch.setattr(QMessageBox,'critical',lambda *args,**kwargs:notices.append(args))
    monkeypatch.setattr('justvedio.gui.MainWindow',lambda:pytest.fail('Expired application must not create its main window'))
    assert main.main()==1
    assert notices==[]
    assert capsys.readouterr()==('','')


@pytest.mark.parametrize('trigger',['timer','start'])
def test_runtime_expiry_stops_and_closes_without_any_message(monkeypatch,trigger):
    app=QApplication.instance() or QApplication([])
    window=MainWindow()
    notices,calls=[],[]
    try:
        wait(app,lambda:window.backend_ready)
        assert window.expiry_timer.isActive()
        assert '2027' not in window.windowTitle()
        monkeypatch.setattr('justvedio.gui.is_expired',lambda:True)
        monkeypatch.setattr(QMessageBox,'critical',lambda *args,**kwargs:notices.append(args))
        monkeypatch.setattr(window.backend,'start_job',lambda *args,**kwargs:calls.append(args))
        if trigger=='timer':
            window.expiry_timer.timeout.emit()
        else:
            window._start('inspect')
        wait(app,lambda:not window.backend.isRunning())
        window._finish_close()
        assert not calls and not notices
        assert window._closing and not window.expiry_timer.isActive()
        assert window._check_expiry() and not notices
    finally:
        window.close()
        wait(app,lambda:not window.backend.isRunning())
        window._finish_close()

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


def test_expired_entry_shows_contact_without_starting_window(monkeypatch):
    import main
    app=QApplication.instance() or QApplication([])
    notices=[]
    monkeypatch.setattr('sys.argv',['justVedio'])
    monkeypatch.setattr(expiry,'is_expired',lambda:True)
    monkeypatch.setattr(QMessageBox,'critical',lambda parent,title,text:notices.append((title,text)))
    monkeypatch.setattr('justvedio.gui.MainWindow',lambda:pytest.fail('Expired application must not create its main window'))
    assert main.main()==1
    assert notices==[('软件已过期','软件已过期，请联系1564532736@qq.com')]


@pytest.mark.parametrize('trigger',['timer','start'])
def test_gui_expiry_blocks_operations_and_closes_worker(monkeypatch,trigger):
    app=QApplication.instance() or QApplication([])
    window=MainWindow()
    notices,calls=[],[]
    try:
        wait(app,lambda:window.backend_ready)
        assert window.expiry_timer.isActive()
        monkeypatch.setattr('justvedio.gui.is_expired',lambda:True)
        monkeypatch.setattr(QMessageBox,'critical',lambda parent,title,text:notices.append(text))
        monkeypatch.setattr(window.backend,'start_job',lambda *args,**kwargs:calls.append(args))
        if trigger=='timer':
            window.expiry_timer.timeout.emit()
        else:
            window._start('inspect')
        wait(app,lambda:not window.backend.isRunning())
        window._finish_close()
        assert not calls and window._closing and not window.expiry_timer.isActive()
        assert notices==[expiry.EXPIRY_MESSAGE]
        assert window._check_expiry() and notices==[expiry.EXPIRY_MESSAGE]
    finally:
        window.close()
        wait(app,lambda:not window.backend.isRunning())
        window._finish_close()
